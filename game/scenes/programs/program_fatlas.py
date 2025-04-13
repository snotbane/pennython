import argparse
import configparser
import json
import os
import re
import sys
import time
from PIL import Image, ImageOps

progress_display = 0


def str2bool(value: str) -> bool:
    if isinstance(value, bool):
        return value
    val = value.lower()
    if val in ('yes', 'true', 't', '1'):
        return True
    elif val in ('no', 'false', 'f', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


def bus_get(section: str, key: str):
	bus.read(bus_path)
	if not (bus.has_section(section) and bus.has_option(section, key)): return None

	result = bus.get(section, key)
	try:
		b = str2bool(result)
		return b
	except:	pass
	return result


def bus_set(section: str, key: str, value):
	bus.read(bus_path)
	value = str(value)
	if not bus.has_section(section): bus.add_section(section)
	bus.set(section, key, value)
	with open(bus_path, 'w') as file:
		bus.write(file, space_around_delimiters=False)


# class Point:
# 	def __init__(self, x: int, y: int):
# 		self.x = x
# 		self.y = y


class Rect:
	def __init__(self, *args):
		if len(args) == 4 and all(isinstance(arg, int) for arg in args):
			self.x, self.y, self.w, self.h = args
		elif len(args) == 2 and all(isinstance(arg, tuple) and len(arg) == 2 for arg in args):
			(self.x, self.y), (self.w, self.h) = args
		else:
			raise TypeError("Expected 4 integers or 2 (x, y) tuples")


	def __repr__(self):
		return f"Rect({self.x}, {self.y} ... {self.w}, {self.h})"


	@property
	def xy(self) -> tuple[int, int]:
		return (self.x, self.y)
	@xy.setter
	def xy(self, value: tuple[int, int]):
		self.x = value[0]
		self.y = value[1]


	@property
	def size(self) -> tuple[int, int]:
		return (self.w, self.h)
	@size.setter
	def size(self, value: tuple[int, int]):
		self.w = value[0]
		self.h = value[1]


	@property
	def r(self) -> int:
		return self.x + self.w
	@r.setter
	def r(self, value):
		self.w = value - self.x


	@property
	def b(self) -> int:
		return self.y + self.h
	@b.setter
	def b(self, value):
		self.h = value - self.y


	@property
	def rb(self) -> tuple[int, int]:
		return (self.r, self.b)
	@rb.setter
	def rb(self, value: tuple[int, int]):
		self.r = value[0]
		self.b = value[1]


	@property
	def area(self) -> int:
		return self.w * self.h


	## Returns true if the other Rect is completely inside self
	def contains(self, other) -> bool:
		if not isinstance(other, Rect):
			raise TypeError("Expected a Rect instance")
		return (
			self.x <= other.x and self.y <= other.y and
			self.r >= other.r and self.b >= other.b
		)

	## Returns true if the Rects touch at all
	def overlaps(self, other) -> bool:
		if not isinstance(other, Rect):
			raise TypeError("Expected a Rect instance")
		return not (
			self.r <= other.x or self.x >= other.r or
			self.b <= other.y or self.y >= other.b
		)

	def union(self, other):
		result = Rect(min(self.x, other.x), min(self.y, other.y), max(self.r, other.r), max(self.b, other.b))
		result.r = result.w
		result.b = result.h
		return result


class PathedImage:
	def __init__(self, root, file):
		self.root = root
		self.file = file
		self.full = os.path.join(root, file)
		self.name, self.ext = os.path.splitext(file)


	def __str__(self):
		return self.file


	@property
	def json_path(self) -> str:
		return os.path.join(self.root, self.name + ".json")


class SourceImage(PathedImage):
	def __init__(self, root: str, file: str, region: Rect = None, bitmap: Image = None):
		super().__init__(root, file)
		self.image : Image = Image.open(self.full).convert("RGBA")
		self.bitmap : Image = bitmap

		self.source_region = region if region != None else \
			Rect(0, 0, self.image.width, self.image.height)
		self.target_offset = (0, 0)
		self.target_match = None

	@property
	def image_cropped(self) -> Image:
		return self.image.crop((self.source_region.x, self.source_region.y, self.source_region.r, self.source_region.b))

	@property
	def json_data(self) -> dict:
		return {
			"name": self.name,
			"source_region": [self.source_region.x, self.source_region.y, self.source_region.w, self.source_region.h],
			"target_offset": self.target_offset,
		}


	@property
	def target_region(self) -> Rect:
		return Rect(self.target_offset, self.source_region.size)


	def add_to_target(self):
		print(f"Added {self.name} to '{self.target}'")
		self.target.add(self)


	def crop_visible(self):
		_, _, _, a = self.image.split()
		a_pixels = a.load()
		w, h = self.image.size

		rx, ry, rw, rh = [-1, -1, -1, -1]
		for x in range(w):
			for y in range(h):
				if a_pixels[x, y] == 0: continue
				print((x, y))
				rx = x
				break
			if rx != -1: break
		for y in range(h):
			for x in range(w):
				if a_pixels[x, y] == 0: continue
				ry = y
				break
			if ry != -1: break
		for x in range(w):
			for y in range(h):
				if a_pixels[w-x-1, h-y-1] == 0: continue
				rw = w - rx - x
				break
			if rw != -1: break
		for y in range(h):
			for x in range(w):
				if a_pixels[w-x-1, h-y-1] == 0: continue
				rh = h - ry - y
				break
			if rh != -1: break

		self.source_region = Rect(rx, ry, rw, rh)


class TargetImage(PathedImage):
	def __init__(self, root, file, format, margin):
		super().__init__(root, file)

		self.sources = []
		self.margin = margin
		self.snaps = [ [ self.margin, self.margin ] ]

		self.image : Image = Image.new(format, [1, 1])
		self.full_rect : Rect = Rect(0, 0, 1, 1)


	def expand(self, size):
		new_size = (size[0] + self.margin, size[1] + self.margin)
		delta = (0, 0, new_size[0] - self.full_rect.w, new_size[1] - self.full_rect.h)
		self.full_rect.size = new_size
		self.image = ImageOps.expand(self.image, delta)


	def add(self, source: SourceImage):
		rect = Rect(self.get_snap_for(source.source_region.size), source.source_region.size)

		if not self.full_rect.contains(rect):
			self.expand(self.full_rect.union(rect).size)

		self.image.paste(source.image_cropped, (rect.x, rect.y))
		source.target_offset = (rect.x, rect.y)

		self.sources.append(source)

		# Remove the existing snap point
		try:
			self.snaps.remove(source.target_offset)
		except ValueError: pass

		## Add new snap points at the top right and bottom left corners, if they don't exist
		snap1 = (source.target_offset[0] + source.source_region.w + self.margin, source.target_offset[1])
		try:
			_ = self.snaps.index(snap1)
		except ValueError:
			self.snaps.append(snap1)
		snap2 = (source.target_offset[0], source.target_offset[1] + source.source_region.h + self.margin)
		try:
			_ = self.snaps.index(snap2)
		except ValueError:
			self.snaps.append(snap2)


	def get_snap_for(self, size: tuple[int, int]) -> tuple[int, int]:
		candidates = []
		for snap in self.snaps:
			query = Rect(snap[0], snap[1], size[0], size[1])
			overlaps = False
			for source in self.sources:
				if source.target_region.overlaps(query):
					overlaps = True
					break
			if not overlaps:
				candidates.append(query)

		if len(candidates) == 0: return self.snaps[0]
		candidates.sort(key=lambda rect: not self.full_rect.contains(rect))
		return (candidates[0].x, candidates[0].y)


	def save(self):
		os.makedirs(os.path.dirname(self.full), exist_ok=True)
		print(f"Saving image to {self.full} ...")
		self.image.save(self.full)
		print(f"Saved image!")


def assign_image_sources():
	result = []
	pattern = re.compile(args.filter_include)
	for root, dirs, files, in os.walk(args.source):
		for file in files:
			if re.search(pattern, file) == None: continue
			source = SourceImage(root, file)
			result.append(source)
	return result


def assign_image_targets(sources):
	pattern = re.compile(args.filter_separate)
	targets_dict = dict()
	for source in sources:
		match_string = re.search(pattern, source.name).group()
		if targets_dict.get(match_string) == None:
			path = f"{args.project_name}{match_string}.png"
			targets_dict[match_string] = TargetImage(args.target, path, args.image_format, args.island_margin)
		source.target_match = match_string
	return (sources, targets_dict)


def assign_comp_data(maps : dict) -> dict:
	result = dict()
	available = list()
	components = set()
	pattern = re.compile(args.filter_composite)
	for k in maps.keys():
		for entry in maps[k]:
			available.append(entry["name"])
			match = re.search(pattern, entry["name"])

			if not match:
				print("One or more matches were not found in the regex; double check your pattern!")
				return dict()

			components.add(match.group(5))
			if result.get(match.group(1)) == None:
				is_latter_index = match.group(3) != None and int(match.group(3)) != 0

				if is_latter_index: result[match.group(1)] = f"{match.group(2)}_{"0".zfill(len(match.group(3)))}"
				else: result[match.group(1)] = None

	for k in result.keys():
		comp = dict()
		index_base_entry = result[k]

		for c in components:
			r_suffix = f"_r_{c}"
			r_name = k + r_suffix
			l_suffix = f"_l_{c}"
			l_name = k + l_suffix

			i = 0
			for m in maps.keys():
				if i == 2: break
				for entry in maps[m]:
					if i == 2: break
					if entry["name"] == r_name:
						comp[r_suffix] = r_name
						i += 1
					elif entry["name"] == l_name:
						comp[l_suffix] = l_name
						i += 1

			if index_base_entry != None and comp.get(r_suffix) == None and result[index_base_entry].get(r_suffix) != None:
				comp[r_suffix] = result[index_base_entry][r_suffix]

			if comp.get(l_suffix) == None and comp.get(r_suffix) != None:
				comp[l_suffix] = comp[r_suffix]


		result[k] = comp
	return result


def main():
	global progress_display

	if not (
		args.project_name != "" and
		os.path.exists(args.source) and
		os.path.exists(args.target)
	):
		sys.exit(1)

	bus_set("output", "progress_display", 0)
	bus_set("output", "progress_display_max", 0)

	sources = assign_image_sources()
	sources, targets = assign_image_targets(sources)
	bus_set("output", "progress_display_max", len(sources))

	project_json_path = os.path.join(args.target, args.project_name + ".json")

	maps_data = dict()

	for source in sources:
		if bus_get("input", "stop"): break

		bus_set("output", "source_preview", f"\"{source.full}\"")
		if args.island_crop:
			print(f"Cropping image '{source.name}' ({progress_display + 1}/{len(sources)}) ...")
			source.crop_visible()
		target = targets[source.target_match]
		print(f"Appending image '{source.name}' to '{target.file}'...")
		target.add(source)
		target.save()
		bus_set("output", "target_updated", f"\"{target.full}\"")


		if maps_data.get(target.file) == None:
			maps_data[target.file] = []
		maps_data[target.file].append(source.json_data)

		progress_display += 1
		bus_set("output", "progress_display", progress_display)

	print(f"Conglomeration complete.")

	comp_data = assign_comp_data(maps_data)

	json_data = {"maps": maps_data, "composites": comp_data}

	os.makedirs(os.path.dirname(project_json_path), exist_ok=True)
	with open(project_json_path, "w") as file:
		json.dump(json_data, file)

	for k in targets.keys():
		targets[k].save()

if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("bus_path", type=str)
	parser.add_argument("project_name", type=str)
	parser.add_argument("source", type=str)
	parser.add_argument("target", type=str)
	parser.add_argument("filter_include", type=str )
	parser.add_argument("filter_separate", type=str)
	parser.add_argument("filter_composite", type=str)
	parser.add_argument("image_format", type=str)
	parser.add_argument("image_size_limit", type=int)
	parser.add_argument("island_crop", type=str2bool)
	parser.add_argument("island_margin", type=int)
	args = parser.parse_args()

	bus_path = args.bus_path
	bus = configparser.ConfigParser()
	bus.read(bus_path)

	main()

	sys.exit(0)
