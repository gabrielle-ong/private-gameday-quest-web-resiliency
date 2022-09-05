# Copyright 2022 Amazon.com and its affiliates; all rights reserved. 
# This file is Amazon Web Services Content and may not be duplicated or distributed without permission.
import os
from datetime import datetime
import boto3
import json
import dynamodb_utils
import quest_const
import output_const
import input_const
import hint_const
import scoring_const
import http.client
import time
from aws_gameday_quests.gdQuestsApi import GameDayQuestsApiClient

# Standard AWS GameDay Quests Environment Variables
QUEST_ID = os.environ['QUEST_ID']
QUEST_API_BASE = os.environ['QUEST_API_BASE']
QUEST_API_TOKEN = os.environ['QUEST_API_TOKEN']
GAMEDAY_REGION = os.environ['GAMEDAY_REGION']

# Quest Environment Variables
QUEST_TEAM_STATUS_TABLE = os.environ['QUEST_TEAM_STATUS_TABLE']
CHAOS_TIMER_MINUTES = os.environ['CHAOS_TIMER_MINUTES']

# Dynamo DB setup
dynamodb = boto3.resource('dynamodb')
quest_team_status_table = dynamodb.Table(QUEST_TEAM_STATUS_TABLE)

# This function is triggered by cron_lambda.py. It performs validation of team actions, such as assuming a role in their
# AWS account to check resources or trigger chaos events, as well as updating progress, or posting a message to the team’s event UI.
# Expected event payload is the QuestsAPI entry for this team
def lambda_handler(event, context):
    print(f"check_team_lambda invocation, event:{json.dumps(event, default=str)}, context: {str(context)}")

    # Instantiate the Quest API Client.
    quests_api_client = GameDayQuestsApiClient(QUEST_API_BASE, QUEST_API_TOKEN)

    # Check if event is running
    event_status = quests_api_client.get_event_status()
    if event_status['status'] != quest_const.EVENT_IN_PROGRESS:
        print(f"Event Status: {event_status}, aborting CHECK_TEAM_LAMBDA")
        return

    dynamodb_response = quest_team_status_table.get_item(Key={'team-id': event['team-id']})
    print(f"Retrieved quest team state for team {event['team-id']}: {json.dumps(dynamodb_response, default=str)}")

    # Make a copy of the original array to be able later on to do a comparison and validate whether a DynamoDB update is needed    
    team_data = dynamodb_response['Item'].copy() # Check init_lambda for the format

    # Task 1 evaluation
    team_data = attach_cloudfront_origin(quests_api_client, team_data)
    
    # Task 2 evaluation
    team_data = evaluate_cloudfront_logging(quests_api_client, team_data)

    # Task 3 evaluation
    team_data = evaluate_access_key(quests_api_client, team_data)

    # Task 4 evaluation
    team_data = evaluate_final_answer(quests_api_client, team_data)

    # Complete quest if everything is done
    check_and_complete_quest(quests_api_client, QUEST_ID, team_data)

    # Compare initial DynamoDB item with its copy to check whether changes were made. 
    if dynamodb_response['Item']==team_data:
        print("No changes throughout this run - no need to update the DynamoDB item")
    else:
        dynamodb_utils.save_team_data(team_data, quest_team_status_table)


# Task 1 evaluation - CloudFront Distribution Origin
def attach_cloudfront_origin(quests_api_client, team_data):
    print(f"Evaluating CloudFront Distribution Origin for team {team_data['team-id']}")

    # Check whether task was completed already
    if not team_data['is-attach-cloudfront-origin-done']:

        # Establish cross-account session
        print(f"Assuming Ops role for team {team_data['team-id']}")
        xa_session = quests_api_client.assume_team_ops_role(team_data['team-id'])

        # Lookup events in CloudFront
        cloudfront_client = xa_session.client('cloudfront')
        quest_start = datetime.fromtimestamp(team_data['quest-start-time'])
        cloudfront_response = cloudfront_client.list_distributions()
        origin_domain_name = cloudfront_response['DistributionList']['Items'][0]['Origins']['Items'][0]['DomainName']
        print(f"CloudFront result for team {team_data['team-id']}: {cloudfront_response}")

        # Complete task if CloudFront Origin was attached
        if origin_domain_name != "www.amazon.com":

            # Switch flag
            team_data['is-attach-cloudfront-origin-done'] = True

            # Delete hint
            response = quests_api_client.delete_hint(
                team_id=team_data['team-id'],
                quest_id=QUEST_ID,
                hint_key=hint_const.TASK1_HINT1_KEY,
                detail=True
            )
            # Handling a response status code other than 200. In this case, we are just logging
            if response['statusCode'] != 200:
                print(response)

            # Post task final message
            quests_api_client.post_output(
                team_id=team_data['team-id'],
                quest_id=QUEST_ID,
                key=output_const.TASK1_COMPLETE_KEY,
                label=output_const.TASK1_COMPLETE_LABEL,
                value=output_const.TASK1_COMPLETE_VALUE,
                dashboard_index=output_const.TASK1_COMPLETE_INDEX,
                markdown=output_const.TASK1_COMPLETE_MARKDOWN,
            )

            # Award final points
            quests_api_client.post_score_event(
                team_id=team_data["team-id"],
                quest_id=QUEST_ID,
                description=scoring_const.TASK1_COMPLETE_DESC,
                points=scoring_const.TASK1_COMPLETE_POINTS
            )

        else:
            print(f"No matching CloudFront events found for team {team_data['team-id']}")

    return team_data

# def evaluate_monitoring(quests_api_client, team_data):
#     print(f"Evaluating monitoring task for team {team_data['team-id']}")

#     # Check whether task was completed already
#     if not team_data['is-monitoring-chaos-done']:

#         # Check if chaos has not started yet and the team has provided the EC2 IP address
#         if not team_data['is-monitoring-chaos-started'] and team_data['is-ip-address']:

#             # Start chaos event if timer is up or task 2 and 3 are done
#             if ((team_data['is-cloudshell-launched']    # Task 2
#                 and team_data['is-accesskey-rotated'])  # Task 3
#                 or is_chaos_timer_up(team_data['monitoring-chaos-timer'],int(CHAOS_TIMER_MINUTES))
#                 ):

#                 print(f"Time for chaos event for team {team_data['team-id']}")

#                 # Switch flag that chaos event has started
#                 team_data['is-monitoring-chaos-started'] = True

#                 # Establish cross-account session
#                 print(f"Assuming Ops role for team {team_data['team-id']}")
#                 xa_session = quests_api_client.assume_team_ops_role(team_data['team-id'])

#                 # Break network connectivity by removing ingress rules
#                 print(f"Removing ingress rules from Security Group {team_data['security-group']}")
#                 security_group = xa_session.resource('ec2').SecurityGroup(team_data['security-group'])
#                 response = security_group.revoke_ingress(
#                     IpPermissions=security_group.ip_permissions
#                 )

#                 # Wait for revoke_ingress call to fully complete
#                 print(f"Waiting for revoke_ingress to be applied to SG {team_data['security-group']}")
#                 while True:
#                     time.sleep(5) # pause a bit to make sure the change is fully applied since it's not instant
#                     response = xa_session.client('ec2').describe_security_groups(GroupIds=[team_data['security-group']])
#                     ingress_size = len(response['SecurityGroups'][0]['IpPermissions'])
#                     if ingress_size == 0:
#                         break
#                     print(f"Waiting a bit longer..")
#                 print(f"revoke_ingress fully applied to SG {team_data['security-group']}")

#                 # Post task 1 hint
#                 quests_api_client.post_hint(
#                     team_id=team_data['team-id'],
#                     quest_id=QUEST_ID,
#                     hint_key=hint_const.TASK1_HINT1_KEY,
#                     label=hint_const.TASK1_HINT1_LABEL,
#                     description=hint_const.TASK1_HINT1_DESCRIPTION,
#                     value=hint_const.TASK1_HINT1_VALUE,
#                     dashboard_index=hint_const.TASK1_HINT1_INDEX,
#                     cost=hint_const.TASK1_HINT1_COST,
#                     status=hint_const.STATUS_OFFERED
#                 )

#         # Award points if web app is up else detract points if down
#         is_webapp_up = check_webapp(team_data)
#         if is_webapp_up:
#             print(f"The web application for team {team_data['team-id']} is UP")
#             quests_api_client.post_score_event(
#                 team_id=team_data["team-id"],
#                 quest_id=QUEST_ID,
#                 description=scoring_const.MONITORING_WEB_APP_UP_DESC,
#                 points=scoring_const.MONITORING_WEB_APP_UP_POINTS
#             )
            
#             # Delete app down message if present
#             quests_api_client.delete_output(
#                 team_id=team_data["team-id"],
#                 quest_id=QUEST_ID, 
#                 key=output_const.TASK1_WEBAPP_DOWN_KEY
#             )
#         else:
#             print(f"The web application for team {team_data['team-id']} is DOWN")
#             quests_api_client.post_score_event(
#                 team_id=team_data["team-id"],
#                 quest_id=QUEST_ID,
#                 description=scoring_const.MONITORING_WEB_APP_DOWN_DESC,
#                 points=scoring_const.MONITORING_WEB_APP_DOWN_POINTS
#             )

#             quests_api_client.post_output(
#                 team_id=team_data['team-id'],
#                 quest_id=QUEST_ID,
#                 key=output_const.TASK1_WEBAPP_DOWN_KEY,
#                 label=output_const.TASK1_WEBAPP_DOWN_LABEL,
#                 value=output_const.TASK1_WEBAPP_DOWN_VALUE,
#                 dashboard_index=output_const.TASK1_WEBAPP_DOWN_INDEX,
#                 markdown=output_const.TASK1_WEBAPP_DOWN_MARKDOWN,
#             )

#         # Complete task if chaos event had started and web app is up
#         if team_data['is-monitoring-chaos-started'] and is_webapp_up:
            
#             # Switch flag
#             team_data['is-monitoring-chaos-done'] = True

#             # Delete hint
#             response = quests_api_client.delete_hint(
#                 team_id=team_data['team-id'],
#                 quest_id=QUEST_ID,
#                 hint_key=hint_const.TASK1_HINT1_KEY,
#                 detail=True
#             )
#             # Handling a response status code other than 200. In this case, we are just logging
#             if response['statusCode'] != 200:
#                 print(response)

#             # Post task final message
#             quests_api_client.post_output(
#                 team_id=team_data['team-id'],
#                 quest_id=QUEST_ID,
#                 key=output_const.TASK1_COMPLETE_KEY,
#                 label=output_const.TASK1_COMPLETE_LABEL,
#                 value=output_const.TASK1_COMPLETE_VALUE,
#                 dashboard_index=output_const.TASK1_COMPLETE_INDEX,
#                 markdown=output_const.TASK1_COMPLETE_MARKDOWN,
#             )

#             # Award final points
#             quests_api_client.post_score_event(
#                 team_id=team_data["team-id"],
#                 quest_id=QUEST_ID,
#                 description=scoring_const.TASK1_COMPLETE_DESC,
#                 points=scoring_const.TASK1_COMPLETE_POINTS
#             )
    
#     return team_data


# Checks whether the monitoring web app is up or done and returns True or False respectively
def check_webapp(team_data):
    try:
        print(f"Testing web app status")
        conn = http.client.HTTPConnection(team_data['ip-address'], timeout=5)
        conn.request("GET", "/index.html")
        res = conn.getresponse()
        data = res.read().decode("utf-8") 
        print(res.status)
        if res.status != 200:
            raise Exception(f"Web app down: {res.status} - {res.reason}")
        return True
    except Exception as e:
        print(f"Web app not available: {e}")
        return False


# Task 2a evaluation - CloudFront logs
def evaluate_cloudfront_logging(quests_api_client, team_data):
    print(f"Evaluating CloudFront Logs task for team {team_data['team-id']}")

    # Check whether task was completed already
    if not team_data['is-cloudfront-logs-enabled']:

        # Establish cross-account session
        print(f"Assuming Ops role for team {team_data['team-id']}")
        xa_session = quests_api_client.assume_team_ops_role(team_data['team-id'])

        # Lookup events in CloudFront
        cloudfront_client = xa_session.client('cloudfront')
        quest_start = datetime.fromtimestamp(team_data['quest-start-time'])
        cloudfront_response = cloudfront_client.list_distributions()
        distribution_id = cloudfront_response['DistributionList']['Items'][0]['Id']
        cloudfront_distribution_response = cloudfront_client.get_distribution(Id=distribution_id)
        logging_flag = cloudfront_distribution_response['Distribution']['DistributionConfig']['Logging']['Enabled']

        print(f"CloudFront result for team {team_data['team-id']}: {logging_flag}")

        # Complete task if CloudShell was launched
        if logging_flag:

            # Switch flag
            team_data['is-cloudfront-logs-enabled'] = True

            # Delete hint
            response = quests_api_client.delete_hint(
                team_id=team_data['team-id'],
                quest_id=QUEST_ID,
                hint_key=hint_const.TASK2_HINT1_KEY,
                detail=True
            )
            # Handling a response status code other than 200. In this case, we are just logging
            if response['statusCode'] != 200:
                print(response)

            # Post task final message
            quests_api_client.post_output(
                team_id=team_data['team-id'],
                quest_id=QUEST_ID,
                key=output_const.TASK2A_COMPLETE_KEY,
                label=output_const.TASK2A_COMPLETE_LABEL,
                value=output_const.TASK2A_COMPLETE_VALUE,
                dashboard_index=output_const.TASK2A_COMPLETE_INDEX,
                markdown=output_const.TASK2A_COMPLETE_MARKDOWN,
            )

            # Award final points
            quests_api_client.post_score_event(
                team_id=team_data["team-id"],
                quest_id=QUEST_ID,
                description=scoring_const.TASK2_COMPLETE_DESC,
                points=scoring_const.TASK2_COMPLETE_POINTS
            )

        else:
            print(f"No matching CloudTrail events found for team {team_data['team-id']}")

    return team_data


# Task 3 - Access Key Rotation
def evaluate_access_key(quests_api_client, team_data):

    # Check whether the team has accepted the challenge and task has not been completed yet
    if team_data['credentials-task-started'] and not team_data['is-accesskey-rotated']:

        # Establish cross-account session
        print(f"Assuming Ops role for team {team_data['team-id']}")
        xa_session = quests_api_client.assume_team_ops_role(team_data['team-id'])
    
        # Check user's access key
        iam_client = xa_session.client('iam')
        keys = iam_client.list_access_keys(UserName='ReferenceDeveloper')
        status = "Not found"
        for key in keys['AccessKeyMetadata']:
            if (key['AccessKeyId'] == team_data['accesskey-value']):
                status = key['Status']
                print(f"Access key exists, checking if its active")
                break
    
        if status == "Active":
            print(f"access key has not been deactivated")

            # Detract points
            quests_api_client.post_score_event(
                team_id=team_data["team-id"],
                quest_id=QUEST_ID,
                description=scoring_const.KEY_NOT_ROTATED_DESC,
                points=scoring_const.KEY_NOT_ROTATED_POINTS
            )
        
        elif status == "Inactive" or status == "Not found":
                    
            print(f"Awarding points. Key has been deactivated or deleted")

            # Switch flag
            team_data['is-accesskey-rotated'] = True

            # Delete hint
            response = quests_api_client.delete_hint(
                team_id=team_data['team-id'],
                quest_id=QUEST_ID,
                hint_key=hint_const.TASK3_HINT1_KEY,
                detail=True
            )
            # Handling a response status code other than 200. In this case, we are just logging
            if response['statusCode'] != 200:
                print(response)

            # Post task final message
            quests_api_client.post_output(
                team_id=team_data['team-id'],
                quest_id=QUEST_ID,
                key=output_const.TASK3_COMPLETE_KEY,
                label=output_const.TASK3_COMPLETE_LABEL,
                value=output_const.TASK3_COMPLETE_VALUE,
                dashboard_index=output_const.TASK3_COMPLETE_INDEX,
                markdown=output_const.TASK3_COMPLETE_MARKDOWN,
            )

            # Award final points
            quests_api_client.post_score_event(
                team_id=team_data["team-id"],
                quest_id=QUEST_ID,
                description=scoring_const.KEY_ROTATED_DESC,
                points=scoring_const.KEY_ROTATED_POINTS
            )

    return team_data


# Task 4 - The ultimate answer
# The actual evaluation happens in Update Lambda. Here is the logic to enable the task
def evaluate_final_answer(quests_api_client, team_data):

    # Enable this task as soon as the team completed all the other tasks
    if (team_data['is-attach-cloudfront-origin-done']           # Task 1
        and team_data['is-cloudfront-logs-enabled']         # Task 2
        and team_data['is-accesskey-rotated']           # Task 3
        and not team_data['is-final-task-enabled']):    # Task 4 (this task not yet enabled)

        # Switch flag
        team_data['is-final-task-enabled'] = True

        # Post Task 4 instructions
        quests_api_client.post_output(
            team_id=team_data['team-id'],
            quest_id=QUEST_ID,
            key=output_const.TASK4_KEY,
            label=output_const.TASK4_LABEL,
            value=output_const.TASK4_VALUE,
            dashboard_index=output_const.TASK4_INDEX,
            markdown=output_const.TASK4_MARKDOWN,
        )
        quests_api_client.post_input(
            team_id=team_data['team-id'],
            quest_id=QUEST_ID,
            key=input_const.TASK4_KEY,
            label=input_const.TASK4_LABEL,
            description=input_const.TASK4_DESCRIPTION,
            dashboard_index=input_const.TASK4_INDEX
        )

    return team_data


# Verify that all tasks have been successfully done and complete the quest if so
def check_and_complete_quest(quests_api_client, quest_id, team_data):

    # Check if everything is done
    if (team_data['is-attach-cloudfront-origin-done']           # Task 1
        and team_data['is-cloudfront-logs-enabled']         # Task 2
        and team_data['is-accesskey-rotated']           # Task 3
        and team_data['is-answer-to-life-correct']):    # Task 4

        # Award quest complete points
        print(f"Team {team_data['team-id']} has completed this quest, posting output and awarding points")
        quests_api_client.post_score_event(
            team_id=team_data["team-id"],
            quest_id=quest_id,
            description=scoring_const.QUEST_COMPLETE_DESC,
            points=scoring_const.QUEST_COMPLETE_POINTS
        )

        # Award quest complete bonus points
        bonus_points = calculate_bonus_points(quests_api_client, quest_id, team_data)
        quests_api_client.post_score_event(
            team_id=team_data["team-id"],
            quest_id=quest_id,
            description=scoring_const.QUEST_COMPLETE_BONUS_DESC,
            points=bonus_points
        )

        # Post quest complete message
        quests_api_client.post_output(
            team_id=team_data['team-id'],
            quest_id=quest_id,
            key=output_const.QUEST_COMPLETE_KEY,
            label=output_const.QUEST_COMPLETE_LABEL,
            value=output_const.QUEST_COMPLETE_VALUE,
            dashboard_index=output_const.QUEST_COMPLETE_INDEX,
            markdown=output_const.QUEST_COMPLETE_MARKDOWN,
        )

        # Complete quest
        quests_api_client.post_quest_complete(team_id=team_data['team-id'], quest_id=quest_id)

        return True

    return False


# Checks whether the chaos event timer is up by calculating the difference between the current time and 
# the timer's start time plus the minutes to trigger the chaos event
def is_chaos_timer_up(timer_start_time, timer_minutes):

    # Timer start time
    start_time = datetime.fromtimestamp(timer_start_time)

    # Current time
    current_time = datetime.now()

    # Time difference
    time_diff = current_time - start_time
    
    # Time difference in minutes
    minutes = int(time_diff.total_seconds() / 60)

    if minutes >= timer_minutes:
        print(f"Chaos event timer is up: {minutes} minutes have elapsed")
        return True
    else:
        print(f"No time for chaos event yet: {timer_minutes - minutes} minutes left")

    return False


# Calculate quest completion bonus points
# This is to reward teams that complete the quest faster
def calculate_bonus_points(quests_api_client, quest_id, team_data):
    quest = quests_api_client.get_quest_for_team(team_data['team-id'], quest_id)

    # Get quest start time
    start_time = datetime.fromtimestamp(quest['quest-start-time'])

    # Get quest end time, that is, current time
    end_time = datetime.now()

    # Calculate elapsed time
    time_diff = end_time - start_time
    minutes = int(time_diff.total_seconds() / 60)

    # Calculate bonus points based on elapsed time
    bonus_points = int(scoring_const.QUEST_COMPLETE_POINTS / minutes * scoring_const.QUEST_COMPLETE_MULTIPLIER)
    print(f"Bonus points on {scoring_const.QUEST_COMPLETE_POINTS} done in {minutes} minutes: {bonus_points}")

    return bonus_points