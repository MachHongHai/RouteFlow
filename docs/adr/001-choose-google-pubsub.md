# Choose Pub/Sub and Emulator

Status: accepted and implemented.

## Context

The portfolio needs a cloud-native event transport with a credential-free local path.

## Decision

Use google-cloud-pubsub for confirmed publication, local pull consumption and private Cloud Run push.

## Alternatives

Kafka, RabbitMQ or database polling alone would increase local operations or reduce GCP parity.

## Trade-offs

The emulator cannot prove cloud IAM or native dead-letter forwarding. Cloud push and local pull have different acknowledgement interfaces.

## Consequences

Transport is at least once; application-level poison quarantine is tested locally and native cloud DLQ remains an account smoke test.
