import json, boto3, uuid
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('smartparcel-instructor-parcels')
sqs = boto3.client('sqs')
QUEUE_URL = None

VALID_STATUSES = ["registered", "picked_up", "in_transit", "delivered"]
ROLES = {"driver": ["POST /parcels", "PUT /parcels/{id}/status", "GET /parcels/{id}"],
         "customer": ["GET /parcels/{id}"],
         "admin": ["POST /parcels", "GET /parcels/{id}", "GET /parcels", "PUT /parcels/{id}/status", "DELETE /parcels/{id}"]}

def get_queue_url():
    global QUEUE_URL
    if not QUEUE_URL:
        QUEUE_URL = sqs.get_queue_url(QueueName='smartparcel-instructor-events')['QueueUrl']
    return QUEUE_URL

def resp(code, body):
    return {"statusCode": code, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}

def lambda_handler(event, context):
    method = event.get("httpMethod", "")
    path = event.get("resource", "")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    role = headers.get("x-user-role", "")
    action = f"{method} {path}"

    if role and role not in ROLES:
        return resp(403, {"error": f"Unknown role: {role}"})
    if role and action not in ROLES.get(role, []):
        return resp(403, {"error": f"Role '{role}' not permitted for {action}"})

    try:
        if method == "POST" and path == "/parcels":
            return create_parcel(event)
        elif method == "GET" and path == "/parcels/{id}":
            return get_parcel(event)
        elif method == "GET" and path == "/parcels":
            return list_parcels(event)
        elif method == "PUT" and path == "/parcels/{id}/status":
            return update_status(event)
        elif method == "DELETE" and path == "/parcels/{id}":
            return delete_parcel(event)
        return resp(404, {"error": "Not found"})
    except Exception as e:
        return resp(500, {"error": str(e)})

def create_parcel(event):
    body = json.loads(event.get("body") or "{}")
    for f in ["sender", "receiver", "address", "email"]:
        if not body.get(f):
            return resp(400, {"error": f"Missing field: {f}"})
    pid = f"PKG-{datetime.now().strftime('%Y')}-{uuid.uuid4().hex[:8]}"
    item = {"parcel_id": pid, "sender": body["sender"], "receiver": body["receiver"],
            "address": body["address"], "email": body["email"], "status": "registered",
            "created_at": datetime.now().isoformat()}
    table.put_item(Item=item)
    return resp(201, {"status": "ok", "parcel_id": pid})

def get_parcel(event):
    pid = event["pathParameters"]["id"]
    r = table.get_item(Key={"parcel_id": pid})
    if "Item" not in r:
        return resp(404, {"error": "Parcel not found"})
    return resp(200, {"status": "ok", "parcel": r["Item"]})

def list_parcels(event):
    params = event.get("queryStringParameters") or {}
    if "status" in params:
        r = table.query(IndexName="status-index", KeyConditionExpression=boto3.dynamodb.conditions.Key("status").eq(params["status"]))
    else:
        r = table.scan()
    return resp(200, {"status": "ok", "parcels": r["Items"]})

def update_status(event):
    pid = event["pathParameters"]["id"]
    body = json.loads(event.get("body") or "{}")
    new_status = body.get("new_status", "")
    if new_status not in VALID_STATUSES:
        return resp(400, {"error": f"Invalid status: {new_status}"})
    r = table.get_item(Key={"parcel_id": pid})
    if "Item" not in r:
        return resp(404, {"error": "Parcel not found"})
    cur = VALID_STATUSES.index(r["Item"]["status"])
    nxt = VALID_STATUSES.index(new_status)
    if nxt <= cur:
        return resp(409, {"error": f"Cannot go from {r['Item']['status']} to {new_status}"})
    table.update_item(Key={"parcel_id": pid}, UpdateExpression="SET #s = :s",
                      ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": new_status})
    try:
        sqs.send_message(QueueUrl=get_queue_url(), MessageBody=json.dumps(
            {"parcel_id": pid, "new_status": new_status, "customer_email": r["Item"].get("email",""), "timestamp": datetime.now().isoformat()}))
    except: pass
    return resp(200, {"status": "ok", "parcel_id": pid, "new_status": new_status})

def delete_parcel(event):
    pid = event["pathParameters"]["id"]
    r = table.get_item(Key={"parcel_id": pid})
    if "Item" not in r:
        return resp(404, {"error": "Parcel not found"})
    if r["Item"]["status"] != "registered":
        return resp(409, {"error": f"Cannot cancel parcel with status: {r['Item']['status']}"})
    table.update_item(Key={"parcel_id": pid}, UpdateExpression="SET #s = :s",
                      ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": "cancelled"})
    return resp(200, {"status": "ok", "parcel_id": pid, "new_status": "cancelled"})
