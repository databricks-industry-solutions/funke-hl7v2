"""
The 'funke.demo' package provides synthetic ADT (Admit/Discharge/Transfer) message
generation for the real-time hospital bed utilization demo.

It defines a fixed hospital network (``facilities``), HL7v2 ADT message builders and a
stateful patient-flow engine (``adt``). These are pure-Python and Spark-free so they can be
unit tested locally and driven from a Databricks job.
"""
