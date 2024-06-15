import yaml

def load_parameters():
    with open("data/parameters.yaml", "r") as f:
        return yaml.safe_load(f)
