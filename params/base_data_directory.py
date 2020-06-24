import os

def base_data_dir():
    # NOTE: this must be the ABSOLUTE path
    PATH_TO_BASE_DIR = '/PATH/TO/BASE/DATA/DIRECTORY'
    if(not os.path.exists(PATH_TO_BASE_DIR)):
        print('\033[31m', "ERROR: Failed to find the Base Data Directory at", PATH_TO_BASE_DIR, '\033[0m')
        os._exit(1) # Failure condition
    return PATH_TO_BASE_DIR
