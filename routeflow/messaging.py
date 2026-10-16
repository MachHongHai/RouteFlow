import os
from collections.abc import Callable

from google.api_core.exceptions import AlreadyExists
from google.cloud import pubsub_v1  # type: ignore[attr-defined]

from routeflow.config import settings


def clients() -> tuple[pubsub_v1.PublisherClient, pubsub_v1.SubscriberClient]:
    cfg = settings()
    if cfg.pubsub_emulator_host:
        if cfg.environment != "local":
            raise ValueError("Emulator host must be empty outside local environment")
        os.environ["PUBSUB_EMULATOR_HOST"] = cfg.pubsub_emulator_host
    return pubsub_v1.PublisherClient(), pubsub_v1.SubscriberClient()


class Publisher:
    def __init__(self) -> None:
        self.client, self.subscriber = clients()
        cfg = settings()
        self.topic_path = self.client.topic_path(cfg.google_cloud_project, cfg.topic)

    def publish(self, data: bytes) -> str:
        return str(self.client.publish(self.topic_path, data).result(timeout=30))


def provision() -> None:
    publisher, subscriber = clients()
    cfg = settings()
    for topic, subscription in [
        (cfg.topic, cfg.subscription),
        ("delivery-dlq", "delivery-dlq-audit"),
    ]:
        path = publisher.topic_path(cfg.google_cloud_project, topic)
        try:
            publisher.create_topic(request={"name": path})
        except AlreadyExists:
            pass
        try:
            subscriber.create_subscription(
                request={
                    "name": subscriber.subscription_path(cfg.google_cloud_project, subscription),
                    "topic": path,
                    "ack_deadline_seconds": 60,
                }
            )
        except AlreadyExists:
            pass
    subscriber.close()


def consume(callback: Callable[[bytes], bool]) -> None:
    import signal
    import threading
    from concurrent.futures import CancelledError

    _, subscriber = clients()
    cfg = settings()
    subscription = subscriber.subscription_path(cfg.google_cloud_project, cfg.subscription)
    stopped = threading.Event()

    def shutdown(*_: object) -> None:
        stopped.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, shutdown)

    def receive(message: pubsub_v1.subscriber.message.Message) -> None:
        try:
            if callback(message.data):
                message.ack()
            else:
                message.nack()
        except Exception:
            message.nack()

    future = subscriber.subscribe(
        subscription, callback=receive, flow_control=pubsub_v1.types.FlowControl(max_messages=8)
    )
    try:
        while not stopped.wait(0.5):
            if future.done():
                future.result()
    finally:
        future.cancel()
        try:
            future.result(timeout=30)
        except CancelledError:
            pass
        subscriber.close()
