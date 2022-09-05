# Copyright 2022 Amazon.com and its affiliates; all rights reserved. 
# This file is Amazon Web Services Content and may not be duplicated or distributed without permission.
import os
import boto3
import json
import datetime
import input_const
import output_const
import hint_const
import cfn_utils
import ui_utils
from aws_gameday_quests.gdQuestsApi import GameDayQuestsApiClient

# Standard AWS GameDay Quests Environment Variables
QUEST_ID = os.environ['QUEST_ID']
QUEST_API_BASE = os.environ['QUEST_API_BASE']
QUEST_API_TOKEN = os.environ['QUEST_API_TOKEN']
GAMEDAY_REGION = os.environ['GAMEDAY_REGION']
ASSETS_BUCKET = os.environ['ASSETS_BUCKET']
ASSETS_BUCKET_PREFIX = os.environ['ASSETS_BUCKET_PREFIX']

# Quest Environment Variables
QUEST_TEAM_STATUS_TABLE = os.environ['QUEST_TEAM_STATUS_TABLE']

# Dynamo DB resource
dynamodb = boto3.resource('dynamodb')
quest_team_status_table = dynamodb.Table(QUEST_TEAM_STATUS_TABLE)

# This function is triggered by sns_lambda.py. It performs Quest initialization actions for a given team, such as 
# adding the team to a DynamoDB table tracking internal progress, or posting a welcome message to the team’s event UI.
# Expected event parameters: {'team_id': team_id}
def lambda_handler(event, context):
    print(f"Quest {QUEST_ID} INIT_LAMBDA invocation, event={json.dumps(event, default=str)}, context={str(context)}")

    # Instantiate the Quest API Client.
    quests_api_client = GameDayQuestsApiClient(QUEST_API_BASE, QUEST_API_TOKEN)

    # Get the team_id from the previous event sent by the Lambda that called this function (sns_lambda)
    team_id = event['team_id']

    # Get team data for this quest
    team_data = quests_api_client.get_team(team_id=team_id)

    # Retrieve CloudFormation stack outputs
    ip_address = cfn_utils.retrieve_team_template_output_value(quests_api_client, QUEST_ID, team_data, "EC2IPAddress")
    security_group = cfn_utils.retrieve_team_template_output_value(quests_api_client, QUEST_ID, team_data, "SecurityGroup")
    accesskey_value = cfn_utils.retrieve_team_template_output_value(quests_api_client, QUEST_ID, team_data, "UserAccessKeyName")

    # Populate the QUEST_TEAM_STATUS_TABLE for this team
    dynamo_put_response = quest_team_status_table.put_item(
        Item={
            'team-id': str(team_id),
            'quest-start-time': int(datetime.datetime.now().timestamp()),
            'ip-address': ip_address,
            'security-group': security_group,
            'is-ip-address': False,
            'is-attach-cloudfront-origin-done': False,
            'is-cloudfront-logs-enabled': False,
            'accesskey-value': accesskey_value,
            'is-accesskey-rotated': False,
            'credentials-task-started': False,
            'is-final-task-enabled': False,
            'is-answer-to-life-correct': False,
            'version': 0 # This is for optimistic locking
        }
    )
    print(f"Created team {team_id} in {QUEST_TEAM_STATUS_TABLE}. Response: {json.dumps(dynamo_put_response, default=str)}")

    # Post welcome message to the team
    quests_api_client.post_output(
        team_id=team_id,
        quest_id=QUEST_ID,
        key=output_const.WELCOME_KEY,
        label=output_const.WELCOME_LABEL,
        value=output_const.WELCOME_VALUE,
        dashboard_index=output_const.WELCOME_INDEX,
        markdown=output_const.WELCOME_MARKDOWN,
    )

    # Post task 1 instructions
    quests_api_client.post_output(
        team_id=team_id,
        quest_id=QUEST_ID,
        key=output_const.TASK1_KEY,
        label=output_const.TASK1_LABEL,
        value=output_const.TASK1_VALUE.format(GAMEDAY_REGION),
        dashboard_index=output_const.TASK1_INDEX,
        markdown=output_const.TASK1_MARKDOWN,
    )

    # Post task 2a instructions
    image_url = ui_utils.generate_signed_or_open_url(ASSETS_BUCKET, f"{ASSETS_BUCKET_PREFIX}curl.jpeg",signed_duration=86400)

    quests_api_client.post_output(
        team_id=team_id,
        quest_id=QUEST_ID,
        key=output_const.TASK2A_KEY,
        label=output_const.TASK2A_LABEL,
        value=output_const.TASK2A_VALUE.format(image_url),
        dashboard_index=output_const.TASK2A_INDEX,
        markdown=output_const.TASK2A_MARKDOWN,
    )

    # quests_api_client.post_input(
    #     team_id=team_data['team-id'],
    #     quest_id=QUEST_ID,
    #     key=input_const.TASK1_ENDPOINT_KEY,
    #     label=input_const.TASK1_ENDPOINT_LABEL,
    #     description=input_const.TASK1_ENDPOINT_DESCRIPTION,
    #     dashboard_index=input_const.TASK1_ENDPOINT_INDEX
    # )

    # Post task 2a hint
    quests_api_client.post_hint(
        team_id=team_data['team-id'],
        quest_id=QUEST_ID,
        hint_key=hint_const.TASK2_HINT1_KEY,
        label=hint_const.TASK2_HINT1_LABEL,
        description=hint_const.TASK2_HINT1_DESCRIPTION,
        value=hint_const.TASK2_HINT1_VALUE,
        dashboard_index=hint_const.TASK2_HINT1_INDEX,
        cost=hint_const.TASK2_HINT1_COST,
        status=hint_const.STATUS_OFFERED
    )

    # Post task 2b instructions
    quests_api_client.post_output(
        team_id=team_id,
        quest_id=QUEST_ID,
        key=output_const.TASK2B_KEY,
        label=output_const.TASK2B_LABEL,
        value=output_const.TASK2B_VALUE,
        dashboard_index=output_const.TASK2B_INDEX,
        markdown=output_const.TASK2B_MARKDOWN,
    )
    quests_api_client.post_input(
        team_id=team_data['team-id'],
        quest_id=QUEST_ID,
        key=input_const.TASK2B_ENDPOINT_KEY,
        label=input_const.TASK2B_ENDPOINT_LABEL,
        description=input_const.TASK2B_ENDPOINT_DESCRIPTION,
        dashboard_index=input_const.TASK2B_ENDPOINT_INDEX
    )

    # Post task 2b hint
    quests_api_client.post_hint(
        team_id=team_data['team-id'],
        quest_id=QUEST_ID,
        hint_key=hint_const.TASK3_HINT1_KEY,
        label=hint_const.TASK3_HINT1_LABEL,
        description=hint_const.TASK3_HINT1_DESCRIPTION,
        value=hint_const.TASK3_HINT1_VALUE,
        dashboard_index=hint_const.TASK3_HINT1_INDEX,
        cost=hint_const.TASK3_HINT1_COST,
        status=hint_const.STATUS_OFFERED
    )

    # Post task 2c instructions
    quests_api_client.post_output(
        team_id=team_id,
        quest_id=QUEST_ID,
        key=output_const.TASK2C_KEY,
        label=output_const.TASK2C_LABEL,
        value=output_const.TASK2C_VALUE,
        dashboard_index=output_const.TASK2C_INDEX,
        markdown=output_const.TASK2C_MARKDOWN,
    )
    quests_api_client.post_input(
        team_id=team_data['team-id'],
        quest_id=QUEST_ID,
        key=input_const.TASK3_READY_KEY,
        label=input_const.TASK3_READY_LABEL,
        dashboard_index=input_const.TASK3_READY_INDEX
    )

    # Post task 2c hint
    quests_api_client.post_hint(
        team_id=team_data['team-id'],
        quest_id=QUEST_ID,
        hint_key=hint_const.TASK3_HINT1_KEY,
        label=hint_const.TASK3_HINT1_LABEL,
        description=hint_const.TASK3_HINT1_DESCRIPTION,
        value=hint_const.TASK3_HINT1_VALUE,
        dashboard_index=hint_const.TASK3_HINT1_INDEX,
        cost=hint_const.TASK3_HINT1_COST,
        status=hint_const.STATUS_OFFERED
    )

    # Post task 3 instructions
    quests_api_client.post_output(
        team_id=team_id,
        quest_id=QUEST_ID,
        key=output_const.TASK3_KEY,
        label=output_const.TASK3_LABEL,
        value=output_const.TASK3_VALUE,
        dashboard_index=output_const.TASK3_INDEX,
        markdown=output_const.TASK3_MARKDOWN,
    )
    quests_api_client.post_input(
        team_id=team_data['team-id'],
        quest_id=QUEST_ID,
        key=input_const.TASK3_READY_KEY,
        label=input_const.TASK3_READY_LABEL,
        dashboard_index=input_const.TASK3_READY_INDEX
    )

    # Post task 3 hint
    quests_api_client.post_hint(
        team_id=team_data['team-id'],
        quest_id=QUEST_ID,
        hint_key=hint_const.TASK3_HINT1_KEY,
        label=hint_const.TASK3_HINT1_LABEL,
        description=hint_const.TASK3_HINT1_DESCRIPTION,
        value=hint_const.TASK3_HINT1_VALUE,
        dashboard_index=hint_const.TASK3_HINT1_INDEX,
        cost=hint_const.TASK3_HINT1_COST,
        status=hint_const.STATUS_OFFERED
    )