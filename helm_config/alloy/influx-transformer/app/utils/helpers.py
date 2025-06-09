import re,os
import sys

def determine_type(value):
    if isinstance(value, str):
        return 'string'
    try:
        int(value)
        return 'int'
    except ValueError:
        pass

    try:
        float(value)
        return 'float'
    except ValueError:
        pass

    if value.lower() in ["true", "false"]:
        return 'boolean'

    return 'unknown'

def parse_line_protocol(payload):
    parts = re.split(r' (?=(?:[^"]*"[^"]*")*[^"]*$)', payload)
    measurement_and_tags = parts[0].split(',')
    measurement = measurement_and_tags[0]
    tags = ','.join(measurement_and_tags[1:])
    fields = parts[1] if len(parts) > 1 else ''
    timestamp = parts[2] if len(parts) > 2 else ''

    if (measurement == 'application.httprequests__active' or measurement ==  'jvm_memory_used' or measurement ==  'jvm_gc_pause' or measurement =='jvm_memory_committed' or measurement =='jvm_memory_max'):
        ##  print(f"custom regex used for measurement: {measurement}")
        ##  Modified regex used to handle escaped spaces in tags.  Chose to only apply to broken metrics
        ##  Resolves issues with a message like
        ##  jvm_memory_max,area=nonheap,component=community-broadcast-billing-listener,datacenter=dlas1,environment=development,feature=community-broadcast-billing-listener,id=Compressed\ Class\ Space,modifier=###,system=community-broadcast,team=unified_services,metric_type=gauge value=1073741824.0 1742934780004
        match = re.search(r"([\S\s]*)\s([\S]*)\s([0-9]*)$", payload)
        measurement_and_tags = match.group(1).split(',')
        tags = ','.join(measurement_and_tags[1:])
        fields = match.group(2) if (match.group(2)) else ''
        timestamp = match.group(3) if (match.group(3)) else ''

    if (len(timestamp)!=19):
    ##  Timestamps with less than 19 length were discovered to not be processed by otel collector.  
    ##  This modification adds "0" so that the length of the resulting timestamp is 19
        timestamp += (19-len(timestamp))*("0")
        print(f"Timestamp length was modified for Measurement: {measurement} ")

    if 'sum=' in fields:
    ## the value of sum was causing some errors in otel because additional tag / value of sum is also created, somewhat potentially causing
    ## A named collision in the resulting data.  final metric name will have _summation rather than _sum.  Seems like "sum" is a protected word
        fields = fields.replace('sum=', 'summation=')
    
    #Tag the messages with the currently running pod to identify as from transformer
    pod_name = os.environ.get("HOSTNAME")
    tags+= f",InfluxTransformerPod={pod_name}"
    print(f"Measurement: {measurement}")
    print(f"Tags: {tags}")
    print(f"Fields: {fields}")
    print(f"Timestamp: {timestamp}")



    sys.stdout.flush()

    return measurement, tags, fields, timestamp

def transform_payload(measurement, tags, fields):
    field_dict = {k: v for k, v in (field.split('=', 1) for field in re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', fields))}
    additional_tags = []
    remaining_fields = []
    all_fields_are_strings = True

    for k, v in field_dict.items():
        if v.startswith('"') and v.endswith('"'):
            v = v.replace(" ", "")
            additional_tags.append(f"{k}={v}")
        else:
            if v.endswith('i'):
                v = v[:-1]
                try:
                    v_int = int(v)
                    remaining_fields.append(f"{k}={v_int}")
                    all_fields_are_strings = False
                except ValueError:
                    additional_tags.append(f"{k}={v}")
            else:
                try:
                    v_float = float(v)
                    remaining_fields.append(f"{k}={v_float}")
                    all_fields_are_strings = False
                except ValueError:
                    v = v.replace(" ", "")
                    additional_tags.append(f"{k}={v}")

    if all_fields_are_strings:
        remaining_fields.append("string_field_indicator=1")

    transformed_tags = f"{tags},{','.join(additional_tags)}" if tags else ','.join(additional_tags)
    transformed_fields = ','.join(remaining_fields)

    return measurement, transformed_tags.rstrip(','), transformed_fields.rstrip(',')
