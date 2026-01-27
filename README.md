if isinstance(joined_owners, str):
    joined_owners = [x.strip() for x in joined_owners.split("|") if x.strip()]

if isinstance(left_owners, str):
    left_owners = [x.strip() for x in left_owners.split("|") if x.strip()]


auditor_verify_streaming_video_strict_order
...    started_owner=Christ1 Christ1
...    joined_owners=Dispatcher_Christ Dispatcher_Christ|Christ2 Christ2|Christ3 Christ3
...    left_owners=Christ3 Christ3|Christ2 Christ2
...    ended_owner=Christ1 Christ1
...    timeout=120
...    poll_interval=2