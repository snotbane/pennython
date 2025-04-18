@tool class_name ParameterBool extends Parameter

signal toggled(is_toggled: bool)

@export var _value : bool :
	get: return $hbox/check_box.button_pressed if $hbox/check_box else false
	set(val):
		if not find_child("check_box"): return
		$hbox/check_box.button_pressed = val
		toggled.emit(val)
