import pytest
from pyspark.sql import SparkSession


@pytest.fixture
def spark_fixture():
    """Fixture to give us a dummy spark context, use like any other fixture"""
    spark = SparkSession.builder.appName("Funke Unit Testing").getOrCreate()
    yield spark
