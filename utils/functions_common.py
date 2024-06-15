def create_resource_name (resource_name, environment, region):
    resource_name = f"{resource_name}-{environment}-{region}"
    return resource_name