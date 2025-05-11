from pdf2image import convert_from_path

print("Start converting...")
images = convert_from_path("temp/ерлан - 861014350896.pdf")
print(f"Got {len(images)} pages")
