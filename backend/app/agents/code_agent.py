import os
from pydantic import BaseModel # type: ignore
from typing import Optional

class CodeGenerationResponse(BaseModel):
    engine: str
    file_name: str
    language: str
    code_content: str

class CodeGenAgent:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("META_LLAMA_API_KEY", "")

    async def generate_script(self, prompt: str, engine: str = "Godot 4") -> CodeGenerationResponse:
        if engine == "Godot 4":
            file_name = "player_controller.gd"
            language = "GDScript"
            code_content = """extends CharacterBody2D

@export var speed : float = 200.0

func _physics_process(delta: float) -> void:
	var direction := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	velocity = direction * speed
	move_and_slide()
"""
        else:  # Unity C#
            file_name = "PlayerController.cs"
            language = "C#"
            code_content = """using UnityEngine;

public class PlayerController : MonoBehaviour
{
    [SerializeField] private float speed = 5f;
    private Vector2 moveInput;
    private Rigidbody2D rb;

    void Start()
    {
        rb = GetComponent<Rigidbody2D>();
    }

    void Update()
    {
        moveInput.x = Input.GetAxisRaw("Horizontal");
        moveInput.y = Input.GetAxisRaw("Vertical");
    }

    void FixedUpdate()
    {
        rb.MovePosition(rb.position + moveInput.normalized * speed * Time.fixedDeltaTime);
    }
}
"""

        return CodeGenerationResponse(
            engine=engine,
            file_name=file_name,
            language=language,
            code_content=code_content
        )