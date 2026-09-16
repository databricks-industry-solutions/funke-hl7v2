import pyspark.sql.functions as F
from funke.parsing.hl7 import HL7v2Msg, HL7v2Schema
from funke.parsing.types import HL7v2Type


def parse_hl7v2_msg(schema: HL7v2Schema = None):
    def parse_hl7v2(msg: str()):
        try:
            return HL7v2Msg(msg, schema).segments
        except:
            return None

    return F.udf(parse_hl7v2, returnType=HL7v2Type)


# @F.udf(returnType=HL7v2Type)
# def parse_hl7v2_(msg: str, schema: HL7v2Schema = None):
#     try:
#         return HL7v2Msg(msg, schema).segments
#     except:
#         return None
