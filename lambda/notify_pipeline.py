import json
import os

import urllib3

http = urllib3.PoolManager()

WEBHOOK_URL_SLACK = os.environ["WEBHOOK_URL_SLACK"]


def gen_message_from_codepipeline_event(event_dict):
    """
    Return message according to the CodePipeline state.
    """

    message = f"""Pipeline {event_dict["detail"]["pipeline"]} in region {event_dict["detail"]["region"]} changed state to {event_dict["detail"]["state"]} """

    return message


def lambda_handler(event, context):
    """
    Handle CodePipeline notifications and send messages to Slack.
    """

    try:
        event_str = event["Records"][0]["Sns"]["Message"]
    except (KeyError, IndexError):
        print("Error: Event is missing required data")
        return

    event_dict = json.loads(event_str)

    # generate message
    message = gen_message_from_codepipeline_event(event_dict)
    if not message:
        print({"statusCode": 200, "body": "No message to return."})
        return
    region = event_dict["region"]
    pipeline = event_dict["detail"]["pipeline"]
    pipeline_url = f"https://{region}.console.aws.amazon.com/codesuite/codepipeline/pipelines/{pipeline}/view?region={region}"

    # Send Slack webhook
    text = f"{message}\n<{pipeline_url}|Visit CodePipeline>"
    msg = {
        "text": text,
    }
    encoded_msg = json.dumps(msg).encode("utf-8")
    resp = http.request("POST", WEBHOOK_URL_SLACK, body=encoded_msg)
    print({"statusCode": resp.status, "body": "Send message."})

    return