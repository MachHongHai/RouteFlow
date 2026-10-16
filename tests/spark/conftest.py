from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture(scope="session")
def spark() -> Iterator[Any]:
    pytest.importorskip("pyspark", reason="Run Spark tests in the optional Docker Spark runtime")
    from routeflow.spark.session import spark_session

    current = spark_session("local[2]")
    current.sparkContext.setLogLevel("ERROR")
    yield current
    current.stop()
