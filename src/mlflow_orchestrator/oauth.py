#!/usr/bin/env python

import requests
import time


class OAuthGithubDeviceFlow:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret

    def authorize(self, scope: str = "user:email") -> dict[str, any]:
        github_authorize_url = (
            f"https://github.com/login/oauth/authorize?client_id={self.client_id}"
        )
        response = requests.get(github_authorize_url)

        data = {"client_id": self.client_id, "scope": scope}
        response = requests.post(
            url="https://github.com/login/device/code",
            json=data,
            headers={"Accept": "application/json"},
        )
        response_data = response.json()

        interval_in_s = response_data["interval"]
        expires_in_s = response_data["expires_in"]
        device_code = response_data["device_code"]

        print(
            f"Visit {response_data['verification_uri']}"
            "and enter user code: {response_data['user_code']}"
        )
        data = self.wait_for_access(
            device_code=device_code,
            interval_in_s=interval_in_s,
            max_wait_time_in_s=expires_in_s,
        )

        return self.verify_token(access_token=data["access_token"])

    def wait_for_access(
        self, device_code: str, interval_in_s: int = 5, max_wait_time_in_s: int = 900
    ) -> dict[str, any]:
        start_time = time.time()
        while (time.time() - start_time) < max_wait_time_in_s:
            time.sleep(interval_in_s)
            data = {
                "client_id": self.client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }
            response = requests.post(
                url="https://github.com/login/oauth/access_token",
                json=data,
                headers={"Accept": "application/json"},
            )
            if response.status_code == 200:
                data = response.json()
                if "access_token" in data:
                    # {
                    #  'access_token': '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',
                    #  'token_type': 'bearer',
                    #  'scope': 'user:email'
                    # }
                    return response.json()
                if "error" in data:
                    print(f"status: {data['error']}\r", end="")
            else:
                break

        raise RuntimeError("Access request failed")

    def verify_token(self, access_token: str) -> dict[str, any]:
        """
        Verify token and return the user data
        """
        data = {"access_token": access_token}
        response = requests.post(
            url=f"https://api.github.com/applications/{self.client_id}/token",
            json=data,
            auth=(self.client_id, self.client_secret),
            headers={
                "Accept": "application/vnd.github+json",
                "X-Github-Api-Version": "2022-11-28",
            },
        )
        if response.status_code == 200:
            return response.json()["user"]

        raise ValueError(f"Failed to validate token: {response.status_code}")
