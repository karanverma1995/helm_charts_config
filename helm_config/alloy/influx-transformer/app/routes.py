import gzip
from io import BytesIO
from flask import Blueprint, request, jsonify
from app.utils.helpers import parse_line_protocol, transform_payload
from app.utils.otlp import push_to_otlp_async
from app import executor

main_bp = Blueprint('main', __name__)

@main_bp.route('/write', methods=['POST'])
def process_payload():
    db = request.args.get('db', '')
    if db == 'ues':
        print("UES DB not accepted")
        return jsonify({"status": "error", "message": "Payload not accepted for db 'ues'."}), 400

    content_encoding = request.headers.get('Content-Encoding', '')

    if content_encoding == 'gzip':
        compressed_data = request.data
        buf = BytesIO(compressed_data)
        with gzip.GzipFile(fileobj=buf, mode='rb') as f:
            payload = f.read().decode('utf-8')
    else:
        payload = request.data.decode('utf-8')

    print(f"DB: {db}")
    precision = request.args.get('precision', '')
    print(f"Precision: {precision}")

    if not payload:
        return jsonify({"status": "error", "message": "No payload provided"}), 400

    print(f"Received Payload: {payload}")
    payload_lines = payload.splitlines()

    results = []
    for line in payload_lines:
        try:
            measurement, tags, fields, timestamp = parse_line_protocol(line)
            transformed_measurement, transformed_tags, transformed_fields = transform_payload(measurement, tags, fields)
            result = executor.submit(push_to_otlp_async, transformed_measurement, transformed_tags, transformed_fields, timestamp)
            result = result.result()
            results.append(result)
        except Exception as e:
            results.append({"status": "error", "message": f"Failed to process payload line: {str(e)}"})
            print("Error in processing payload line.  The following line may have caused an issue: ")
            print(line)            

    return jsonify({"status": "success", "results": results})
