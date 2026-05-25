
import os

# change this to your root folder
root_folder = r"C:\Users\Administrator\Documents\docuflow_ai"

for folder_path, folder_names, file_names in os.walk(root_folder):

    print(f"\nFOLDER: {folder_path}")

    for file in file_names:
        print("   ", file)

