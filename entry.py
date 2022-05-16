import sys
import json
import requests
import jsonschema
import copy

class SMConfigSchema:
    schema = {
        "type": "object",
        "properties": {
            "enabled": {"type": "boolean"},
            "items": {
                "type": "array",
                "items": {"$ref": "#/$defs/item"}
            },
            "version": {"type": "string"}
        },
        "required": ["enabled", "items", "version"],

        "$defs": {
            "item": {
                "type": "object",
                "properties": {
                    "package": {"type": "string"},
                    "config_files": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/cfg"}
                    },
                    "parameters": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/param"}
                    }
                },
                "required": ["config_files"]
            },
            "cfg": {
                "type": "object",
                "properties": {
                    "config_template": {"type": "string"},
                    "config_location": {"type": "string"},
                },
                "required": ["config_template","config_location"]
            },
            "param":{
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                }
            }
        }
    }

    @staticmethod
    def validate(jsonData: str):
        jsonschema.validate(instance=jsonData, schema=SMConfigSchema.schema)

class Modes:
    @staticmethod
    def get_mode_add() -> str:
        return "add"
    @staticmethod
    def get_mode_replace() -> str:
        return "replace"
    @staticmethod
    def get_mode_not_present() -> str:
        return "if_not_present"

class InputReader:
    def __init__(self):
        self.props = [
            "token",
            "config_file",
            "mode",
            "device_group",
            "commit_message"
        ]
        self.settings = {}
        self.valid_modes = [
            Modes.get_mode_add(),
            Modes.get_mode_replace(),
            Modes.get_mode_not_present()
        ]
        self.jsonData = None

    def get_input(self):
        if(len(sys.argv) != len(self.props)+1):
            print("wrong number of input arguments")
            print(f"expecting: {len(self.props)}, got: {len(sys.argv)-1}")
            print("provide values for: ", self.props)
            print("got: ", sys.argv)
            sys.exit(1)
        for i,key in enumerate(self.props):
            self.settings[key] = sys.argv[i+1]

        if(self.settings["mode"] not in self.valid_modes):
            print("invalid mode chosen:", self.settings["mode"])
            print("available options are:", self.valid_modes)
            sys.exit(1)

    def __str__(self) -> str:
        return json.dumps(self.settings)

    def get_config(self):
        self.is_ready()
        if(not self.jsonData):
            with open(self.settings["config_file"],"r") as f:
                self.jsonData = json.load(f)
                SMConfigSchema.validate(self.jsonData)
        return self.jsonData

    def is_ready(self) -> bool:
        if(not self.settings):
            print("call get_input before using get_config in InputReader")
            sys.exit(1)
        return True

    def get(self, key:str) -> str:
        return self.settings[key]

class ApiCalls:
    base_url = "https://www.app.qbee.io/api/v2/"
    change_api = "change"
    commit_api = "commit"
    config_api = "config/"
    software_management = "software_management"

    def __init__(self, node_id:str, config:str, commit_msg: str) -> None:
        self.node_id = node_id
        self.change_param = {
            "node_id": node_id,
            "config": config,
            "formtype": ApiCalls.software_management
        }
        self.commit_param = {
            "action": "commit",
            "message": commit_msg
        }
        self.s = requests.Session()
        self.session_init = False

    def update_session(self,token:str) -> None:
        self.session_init = True
        headers = {
            'Authorization': "Bearer " + token
        }
        self.s.headers.update(headers)

    def get_current_config(self):
        self.session_checker()
        req = self.s.get(ApiCalls.get_config_api(self.node_id))
        self.api_validator(req)
        current_config = req.json()
        return current_config

    def session_checker(self):
        if(not self.session_init):
            print("You need to assign a session to the API caller before making an API call")
            sys.exit(1)

    def api_validator(self,req:requests.Response):
        if req.status_code != 200:
            print(req.json())
            print("error in API call... aborting...")
            sys.exit(1)

    def get_cfg_config(self):
        return json.loads(self.change_param["config"])

    def set_fd_config(self,config):
        self.change_param["config"] = json.dumps(config)


    @staticmethod
    def get_change_api() -> str:
        return ApiCalls.base_url + ApiCalls.change_api

    @staticmethod
    def get_commit_api() -> str:
        return ApiCalls.base_url + ApiCalls.commit_api

    @staticmethod
    def get_config_api(node_id:str) -> str:
        return ApiCalls.base_url + ApiCalls.config_api + node_id

    def send_config(self):
        self.session_checker()
        req = self.s.post(ApiCalls.get_change_api(), data=self.change_param)
        print("posting new config")
        self.api_validator(req)
        print("success: ", req.json())
        print("commiting new config")
        req = self.s.post(ApiCalls.get_commit_api(), data=self.commit_param)
        self.api_validator(req)
        print("success: ", req.json())

class ConfigHandler:
    def __init__(self, in_reader:InputReader) -> None:
        self.in_reader = in_reader
        in_reader.is_ready()
        #
        self.ApiCaller = ApiCalls(
            node_id     = in_reader.get("device_group"),
            config      = json.dumps(in_reader.get_config()),
            commit_msg  = in_reader.get("commit_message")
        )
        self.ApiCaller.update_session(in_reader.get("token"))
        #
        self.mode = in_reader.get("mode")

    def exec(self) ->None:
        current_config = self.ApiCaller.get_current_config()
        has_config = self.ApiCaller.software_management in current_config["config"]["bundles"]

        if self.mode == Modes.get_mode_not_present():
            if has_config:
                # nothing to do: config is already there
                print("configuration is already present: not changing anything")
                return
            else:
                print("no configuration present: creating  new configuration")
                self.ApiCaller.send_config()
        elif self.mode == Modes.get_mode_add():
            print("add config to existing")
            if has_config:
                self.__handle_add_config__(current_config)
            else:
                self.ApiCaller.send_config()
        elif self.mode == Modes.get_mode_replace():
            print("replacing config")
            self.ApiCaller.send_config()
        else:
            print("unknown mode: ", self.mode)
            sys.exit(1)

    def __handle_add_config__(self,current_config):
        current_cfg = current_config["config"]["bundle_data"][self.ApiCaller.software_management]
        new_cfg = copy.deepcopy(current_cfg)
        cfg_to_upload = self.ApiCaller.get_cfg_config()

        if( cfg_to_upload["enabled"] != new_cfg["enabled"] ):
            print("missmatch in current configuration and new configuration: set 'enabled' to true or false for both")
            sys.exit(1)
        if( cfg_to_upload["version"] != new_cfg["version"] ):
            print("missmatch in current configuration and new configuration: use 'version' for both")
            sys.exit(1)

        for item in cfg_to_upload["items"]:
            if item not in current_cfg['items']:
                new_cfg['items'].append(item)
            else:
                print("software management entry is already present: ", item)
                print("skipping")

        if(new_cfg == current_cfg):
            print("no config changes: no new software management upload")
        else:
            print("creating new configuration")
            self.ApiCaller.set_fd_config(new_cfg)
            self.ApiCaller.send_config()


if __name__ == "__main__":

    in_reader = InputReader()
    in_reader.get_input()
    in_reader.get_config()

    cf_handler = ConfigHandler(in_reader)
    cf_handler.exec()
    #print(in_reader)
    #MyJsonSchema.validate()



