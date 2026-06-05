extends CharacterBody2D

@export var speed: float = 300.0

func _ready() -> void:
	add_to_group("player")

func _physics_process(_delta: float) -> void:
	var direction := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	velocity = direction * speed
	move_and_slide()
