from pyspark.sql import types as T

# Spark type for an HL7v2 field
HL7v2FieldType = T.MapType(
    T.IntegerType(),
    T.ArrayType(
        T.MapType(
            T.IntegerType(),
            T.MapType(T.IntegerType(), T.StringType()),
        )
    ),
)

# Spark type for a complete HL7v2 message
HL7v2Type = T.MapType(
    T.StringType(),
    T.ArrayType(
        T.StructType(
            [
                T.StructField("index", T.IntegerType()),
                T.StructField("segment", T.StringType()),
                T.StructField("fields", HL7v2FieldType),
            ]
        )
    ),
    True,
)
