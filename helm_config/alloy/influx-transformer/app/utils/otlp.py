import requests
import sys
import os
import warnings
from urllib3.exceptions import InsecureRequestWarning

warnings.simplefilter('ignore', InsecureRequestWarning)

def push_to_otlp_async(measurement, tags, fields, timestamp):
    otlp_url = os.getenv('OTLP_URL')
    if otlp_url is None:
        raise ValueError("The OTLP_URL environment variable is not set")

    line_protocol = f"{measurement},{tags} {fields} {timestamp}"
    headers = {"Content-Type": "text/plain"}

    print(f"Line Protocol: {line_protocol}")
    sys.stdout.flush()

    try:
        response = requests.post(otlp_url, data=line_protocol, headers=headers, verify=False)

        if response.status_code == 204:
            print("Data successfully pushed to OTLP Influx receiver.")
            sys.stdout.flush()
            return {"status": "success", "message": "Data successfully pushed to OTLP Influx receiver."}

        error_message = response.content.decode('utf-8') if isinstance(response.content, bytes) else response.content
        print(f"Failed to push data. Status code: {response.status_code}")
        print(f"Error details: {error_message}")
        sys.stdout.flush()
        return {
            "status": "error",
            "message": f"Failed to push data. Status code: {response.status_code}",
            "details": error_message
        }

    except requests.exceptions.Timeout:
        print("Request to OTLP timed out.")
        sys.stdout.flush()
        return {"status": "error", "message": "Request to OTLP timed out."}

    except requests.exceptions.RequestException as e:
        print(f"Request to OTLP failed: {str(e)}")
        sys.stdout.flush()
        return {"status": "error", "message": f"Request to OTLP failed: {str(e)}"}

    except Exception as e:
        print(f"An unexpected error occurred: {str(e)}")
        sys.stdout.flush()
        return {"status": "error", "message": f"An unexpected error occurred: {str(e)}"}
