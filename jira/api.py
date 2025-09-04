"""
Jira API Client - All Jira REST operations
"""

import base64
from typing import Dict, List, Optional

import requests


class JiraAPI:
    def __init__(self, config):
        self.base_url = config.jira_base_url.rstrip("/")
        self.email: Optional[str] = getattr(config, "jira_email", None)
        self.api_token: Optional[str] = getattr(config, "jira_api_token", None)         # Cloud (Basic)
        self.bearer_token: Optional[str] = getattr(config, "jira_bearer_token", None)   # Server/DC (PAT)
        self.session = requests.Session()

        # Auth selection: prefer Cloud Basic when email+api_token present.
        if self.email and self.api_token:
            print("Using Basic Auth (email + API token)")
            credentials = base64.b64encode(f"{self.email}:{self.api_token}".encode()).decode()
            self.session.headers.update({
                "Authorization": f"Basic {credentials}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Jira-AI-Bot/1.0",
            })
        elif self.bearer_token:
            print("Using Bearer Token Auth (Server/DC PAT)")
            self.session.headers.update({
                "Authorization": f"Bearer {self.bearer_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Jira-AI-Bot/1.0",
            })
        else:
            print("No authentication configured")

        # Optional: quick probe to make /health reliable during setup
        try:
            r = self.session.get(f"{self.base_url}/rest/api/3/myself", timeout=10)
            print(f"Jira probe /myself → {r.status_code}")
        except Exception as e:
            print(f"Jira probe error: {e}")

    def test_connection(self) -> Dict:
        """Test API connection"""
        try:
            response = self.session.get(f"{self.base_url}/rest/api/3/myself")
            if response.status_code == 200:
                user_data = response.json()
                print(f"Connected to Jira as: {user_data.get('displayName', 'Unknown')}")
                return {"success": True, "user": user_data}
            else:
                print(f"Connection test failed: {response.status_code}")
                return {"error": f"HTTP {response.status_code}", "body": response.text[:300]}
        except Exception as e:
            print(f"Connection test failed: {e}")
            return {"error": str(e)}

    def get_issue(self, issue_key: str) -> Dict:
        """Get issue details"""
        try:
            response = self.session.get(f"{self.base_url}/rest/api/3/issue/{issue_key}")
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"HTTP {response.status_code}: {response.text[:300]}"}
        except Exception as e:
            return {"error": str(e)}

    def update_issue(self, issue_key: str, fields: Dict) -> Dict:
        """Update issue fields"""
        try:
            payload = {"fields": fields}
            response = self.session.put(f"{self.base_url}/rest/api/3/issue/{issue_key}", json=payload)
            
            if response.status_code == 204:  # No content response for successful updates
                return {"success": True}
            elif response.status_code == 200:
                return {"success": True, "data": response.json()}
            else:
                return {"error": f"HTTP {response.status_code}: {response.text[:300]}"}
        except Exception as e:
            return {"error": str(e)}

    def get_all_custom_fields(self) -> Dict:
        """Get all custom fields in the Jira instance"""
        try:
            url = f"{self.base_url}/rest/api/3/field"
            print("Fetching all custom fields...")

            response = self.session.get(url)
            response.raise_for_status()

            fields = response.json()
            custom_fields = [f for f in fields if f.get("custom", False)]

            print(f"Found {len(custom_fields)} custom fields in Jira")
            return {"success": True, "fields": custom_fields}

        except Exception as e:
            print(f"Failed to fetch custom fields: {e}")
            return {"error": str(e)}

    def check_duplicate_field(self, field_name: str) -> Dict:
        """Check if a custom field with similar name already exists"""
        try:
            all_fields = self.get_all_custom_fields()

            if "error" in all_fields:
                return all_fields

            field_name_lower = field_name.lower().strip()
            duplicates = []
            similar = []

            for field in all_fields["fields"]:
                existing_name = field.get("name", "").lower().strip()
                field_id = field.get("id", "")

                if existing_name == field_name_lower:
                    duplicates.append({
                        "id": field_id,
                        "name": field.get("name", ""),
                        "type": "exact"
                    })
                elif (field_name_lower in existing_name or existing_name in field_name_lower):
                    similar.append({
                        "id": field_id,
                        "name": field.get("name", ""),
                        "type": "similar"
                    })

            return {
                "success": True,
                "duplicates": duplicates,
                "similar": similar,
                "total_checked": len(all_fields["fields"]),
            }

        except Exception as e:
            print(f"Failed to check duplicates: {e}")
            return {"error": str(e)}

    def create_custom_field(self, field_name: str, field_type: str,
                            description: str = "", options: Optional[List[str]] = None) -> Dict:
        """Create a new custom field"""
        try:
            type_mapping = {
                "select": "com.atlassian.jira.plugin.system.customfieldtypes:select",
                "multiselect": "com.atlassian.jira.plugin.system.customfieldtypes:multiselect",
                "text": "com.atlassian.jira.plugin.system.customfieldtypes:textfield",
                "textarea": "com.atlassian.jira.plugin.system.customfieldtypes:textarea",
                "number": "com.atlassian.jira.plugin.system.customfieldtypes:float",
                "date": "com.atlassian.jira.plugin.system.customfieldtypes:datepicker",
            }

            jira_field_type = type_mapping.get(field_type.lower(), type_mapping["text"])

            payload = {
                "name": field_name,
                "description": description or f"Custom field: {field_name}",
                "type": jira_field_type,
                "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
            }

            if "select" in jira_field_type:
                payload["searcherKey"] = "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher"
            elif "date" in jira_field_type:
                payload["searcherKey"] = "com.atlassian.jira.plugin.system.customfieldtypes:daterange"
            elif "number" in jira_field_type or "float" in jira_field_type:
                payload["searcherKey"] = "com.atlassian.jira.plugin.system.customfieldtypes:exactnumber"

            print(f"Creating custom field: {field_name}")
            print(f"   Type: {jira_field_type}")

            url = f"{self.base_url}/rest/api/3/field"
            response = self.session.post(url, json=payload)

            if response.status_code == 201:
                field_data = response.json()
                field_id = field_data.get("id")
                print(f"Field created successfully! ID: {field_id}")

                if options and "select" in jira_field_type and field_id:
                    print(f"Adding {len(options)} options to select field...")
                    options_result = self.add_field_options(field_id, options)
                    field_data["options_result"] = options_result

                return {"success": True, "field": field_data}
            else:
                print(f"Field creation failed: {response.status_code}")
                return {"error": f"HTTP {response.status_code}: {response.text[:300]}"}

        except Exception as e:
            print(f"Field creation error: {e}")
            return {"error": str(e)}

    def add_field_options(self, field_id: str, options: List[str]) -> Dict:
        """Add options to a select/multiselect custom field"""
        try:
            config_url = f"{self.base_url}/rest/api/3/field/{field_id}/contexts"
            print(f"Getting field contexts for {field_id}...")

            config_response = self.session.get(config_url)
            if config_response.status_code != 200:
                return {"error": "Failed to get field contexts"}

            contexts = config_response.json()
            if not contexts.get("values"):
                return {"error": "No field contexts found"}

            context_id = contexts["values"][0]["id"]
            print(f"Using context ID: {context_id}")

            options_url = f"{self.base_url}/rest/api/3/field/{field_id}/context/{context_id}/option"

            created_options = []
            for option_value in options:
                payload = {"options": [{"value": option_value}]}

                print(f"   Adding option: {option_value}")
                response = self.session.post(options_url, json=payload)

                if response.status_code == 201:
                    option_data = response.json()
                    created_options.extend(option_data.get("options", []))
                    print(f"   Option '{option_value}' added")
                else:
                    print(f"   Failed to add option '{option_value}'")

            return {
                "success": True,
                "options_created": len(created_options),
                "options": created_options,
                "context_id": context_id,
            }

        except Exception as e:
            print(f"Options creation error: {e}")
            return {"error": str(e)}

    def add_comment(self, issue_key: str, comment: str) -> Dict:
        """Add comment to issue"""
        try:
            payload = {
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": comment}],
                        }
                    ],
                }
            }

            url = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment"
            print(f"Adding comment to {issue_key}...")

            response = self.session.post(url, json=payload)

            if response.status_code == 201:
                print("Comment added successfully!")
                return {"success": True, "comment_id": response.json().get("id")}
            else:
                print(f"Comment failed: {response.status_code}")
                return {"error": f"HTTP {response.status_code}: {response.text[:300]}"}

        except Exception as e:
            print(f"Comment error: {e}")
            return {"error": str(e)}