extends Node

@export var total_coins: int = 0

var coin_count: int = 0

@onready var score_label: Label = $"../UI/ScoreLabel"
@onready var win_label: Label = $"../UI/WinLabel"

func _ready() -> void:
	_update_score()
	win_label.hide()
	# Connect to all coin instances dynamically
	for coin in get_tree().get_nodes_in_group("coins"):
		if coin.has_signal("collected"):
			coin.collected.connect(_on_coin_collected)

func _on_coin_collected() -> void:
	add_coin()

func add_coin() -> void:
	coin_count += 1
	_update_score()
	if coin_count >= total_coins:
		_show_win()

func _update_score() -> void:
	score_label.text = "Score: %d / %d" % [coin_count, total_coins]

func _show_win() -> void:
	win_label.show()
