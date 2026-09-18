import asyncio
import unittest

from fastapi import HTTPException
from starlette.requests import Request

import main
from models import CollectionTask


def _request(authorization: str = "") -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/agent/tasks/next",
        "headers": headers,
    })


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.previous_token = main.AGENT_TOKEN
        self.previous_mode = main.COLLECTOR_MODE
        main.AGENT_TOKEN = "test-token"

    def tearDown(self):
        main.AGENT_TOKEN = self.previous_token
        main.COLLECTOR_MODE = self.previous_mode

    def test_agent_requires_matching_bearer_token(self):
        main._require_agent(_request("Bearer test-token"))
        with self.assertRaises(HTTPException) as context:
            main._require_agent(_request("Bearer wrong-token"))
        self.assertEqual(context.exception.status_code, 401)

    def test_agent_mode_rejects_requests_when_not_configured(self):
        main.COLLECTOR_MODE = "agent"
        main.AGENT_TOKEN = ""
        with self.assertRaises(HTTPException) as context:
            asyncio.run(main.collect(main.CollectIn(query="python")))
        self.assertEqual(context.exception.status_code, 503)

    def test_task_payload_exposes_status_without_internal_id(self):
        task = CollectionTask(
            public_id="550e8400-e29b-41d4-a716-446655440000",
            query="python",
            location="Lyon",
            limit=10,
            source="indeed",
            status="pending",
        )
        payload = main._task_payload(task)
        self.assertEqual(payload["task_id"], task.public_id)
        self.assertEqual(payload["status"], "pending")
        self.assertNotIn("id", payload)


if __name__ == "__main__":
    unittest.main()
