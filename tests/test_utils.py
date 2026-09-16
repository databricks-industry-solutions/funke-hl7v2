from funke.utils import parse_hl7_version
from funke.schema.version import HL7Version


def test_parse_hl7_version(spark_fixture):
    spark = spark_fixture

    test_message = """MSH|^~\\&|SIMHOSP|SFAC|RAPP|RFAC|20200508130643||ADT^A01|5|T|2.3|||AL||44|ASCII
    """
    test_message_df = spark.createDataFrame([{"hl7": test_message}])
    test_message_df = test_message_df.withColumn(
        "version", parse_hl7_version(test_message_df.hl7)
    )

    print(test_message_df.rdd.collect())
    assert test_message_df.rdd.collect()[0].version == "2.3"

    test_message_2 = """MSH|^~\\&|SIMHOSP|SFAC|RAPP|RFAC|20200508130643||ADT^A01|5|T|2.8.1|||AL||44|ASCII
    EVN|A01|20200508130643|||C006^Wolf^Kathy^^^Dr^^^DRNBR^PRSNL^^^ORGDR|
    PID|1|2590157853^^^SIMULATOR MRN^MRN|2590157853^^^SIMULATOR MRN^MRN~2478684691^^^NHSNBR^NHSNMBR||Esterkin^AKI Scenario 6^^^Miss^^CURRENT||19890118000000|F|||170 Juice Place^^London^^RW21 6KC^GBR^HOME||020 5368 1665^HOME|||||||||R^Other - Chinese^^^||||||||
    PD1|||FAMILY PRACTICE^^12345|
    PV1|1|I|RenalWard^MainRoom^Bed 1^Simulated Hospital^^BED^Main Building^5|28b|||C006^Wolf^Kathy^^^Dr^^^DRNBR^PRSNL^^^ORGDR|||MED|||||||||6145914547062969032^^^^visitid||||||||||||||||||||||ARRIVED|||20200508130643||"""
    test_message_df = spark.createDataFrame([{"hl7": test_message_2}])
    test_message_df = test_message_df.withColumn(
        "version", parse_hl7_version(test_message_df.hl7)
    )

    print(test_message_df.rdd.collect())
    assert test_message_df.rdd.collect()[0].version == "2.8.1"
