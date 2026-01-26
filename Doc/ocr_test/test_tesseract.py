import pytesseract
import cv2

img = cv2.imread("doc_ci.jpg")
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

text = pytesseract.image_to_string(
    gray,
    lang="ron",
    config="--oem 1 --psm 6"
)

print(text)


import pytesseract, os, subprocess, sys

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
os.environ["TESSDATA_PREFIX"] = r"C:\Program Files\Tesseract-OCR"

print("Python:", sys.version)
print("stdout encoding:", sys.stdout.encoding)

# What languages does tesseract say it has?
print(subprocess.check_output([pytesseract.pytesseract.tesseract_cmd, "--list-langs"], text=True))