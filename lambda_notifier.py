import json, boto3

sns = boto3.client('sns')
TOPIC_ARN = None

def get_topic_arn():
    global TOPIC_ARN
    if not TOPIC_ARN:
        for t in sns.list_topics()['Topics']:
            if 'smartparcel-instructor-alerts' in t['TopicArn']:
                TOPIC_ARN = t['TopicArn']
                break
    return TOPIC_ARN

def lambda_handler(event, context):
    for record in event['Records']:
        try:
            body = json.loads(record['body'])
            msg = f"SmartParcel Update\n\nParcel: {body['parcel_id']}\nNew Status: {body['new_status']}\nCustomer: {body.get('customer_email','N/A')}\nTime: {body.get('timestamp','N/A')}"
            arn = get_topic_arn()
            if arn:
                sns.publish(TopicArn=arn, Subject=f"Parcel {body['parcel_id']} - {body['new_status']}", Message=msg)
            print(f"Notified: {body['parcel_id']} -> {body['new_status']}")
        except Exception as e:
            print(f"Error processing record: {e}")
            raise
    return {'statusCode': 200}
