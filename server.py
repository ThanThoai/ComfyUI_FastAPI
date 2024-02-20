import os
import comfy
import sys
import uuid
import execution
from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from loguru import logger


class Server:

    def __init__(self, app: FastAPI):

        self.router = APIRouter()
        self.app = app
        self.on_prompt_handlers = []

    def add_api_route(self, path: str, endpoint, **kwargs):
        return self.app.add_api_route(path, endpoint, **kwargs)

    def system_info(self, request):
        device = comfy.model_manager.get_torch_device()
        device_name = comfy.model_manager.get_torch_device_name(device)
        vram_total, torch_vram_total = comfy.model_management.get_total_memory(
            device, torch_total_too=True
        )
        vram_free, torch_vram_free = comfy.model_management.get_free_memory(
            device, torch_free_too=True
        )
        system_stats = {
            "system": {
                "os": os.name,
                "python_version": sys.version,
                "embedded_python": os.path.split(os.path.split(sys.executable)[0])[1]
                == "python_embeded",
            },
            "devices": [
                {
                    "name": device_name,
                    "type": device.type,
                    "index": device.index,
                    "vram_total": vram_total,
                    "vram_free": vram_free,
                    "torch_vram_total": torch_vram_total,
                    "torch_vram_free": torch_vram_free,
                }
            ],
        }
        return system_stats

    def execute_workflow(self, request: Request):
        json_data = request.json()
        json_data = self.trigger_on_prompt(json_data)

        if "number" in json_data:
            number = float(json_data["number"])
        else:
            number = self.number
            if "front" in json_data and json_data["front"]:
                number = -number
            self.number += 1
        if "prompt" in json_data:
            prompt = json_data["prompt"]
            valid = execution.validate_prompt(prompt)
            extra_data = {}
            if "extra_data" in json_data:
                extra_data = json_data["extra_data"]

            if "client_id" in json_data:
                extra_data["client_id"] = json_data["client_id"]
            if valid[0]:
                prompt_id = str(uuid.uuid4())
                outputs_to_execute = valid[2]
                self.prompt_queue.put(
                    (number, prompt_id, prompt, extra_data, outputs_to_execute)
                )
                response = {
                    "prompt_id": prompt_id,
                    "number": number,
                    "node_errors": valid[3],
                }
                return JSONResponse(content=response, status_code=status.HTTP_200_OK)
            else:
                logger.info("Invalid prompt:", valid[1])
                return JSONResponse(
                    content={"error": valid[1], "node_errors": valid[3]},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
        else:
            return JSONResponse(
                content={"error": "no prompt", "node_errors": []},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    def add_on_prompt_handler(self, handler):
        self.on_prompt_handlers.append(handler)

    def trigger_on_prompt(self, json_data):
        for handler in self.on_prompt_handlers:
            try:
                json_data = handler(json_data)
            except Exception as e:
                logger.exception(e)

        return json_data
