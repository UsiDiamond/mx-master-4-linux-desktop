cmake_minimum_required(VERSION 3.20)
project(mx4d VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Extra module paths (populated after ECM is found)
find_package(ECM REQUIRED NO_MODULE)
list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH} ${CMAKE_SOURCE_DIR}/cmake)

include(KDEInstallDirs)
include(KDECompilerSettings)
include(KDECMakeSettings)
include(ECMSetupVersion)

ECMSetupVersion(${PROJECT_VERSION}
    VARIABLE_PREFIX MX4D
    VERSION_HEADER "${CMAKE_CURRENT_BINARY_DIR}/mx4d_version.h"
)

# Qt6
find_package(Qt6 REQUIRED COMPONENTS Core DBus Widgets Quick)
qt_standard_project_setup()

# hidapi (via cmake/FindHidapi.cmake)
find_package(Hidapi REQUIRED)

# Subdirectories
add_subdirectory(libmx4hidpp)
add_subdirectory(daemon)
add_subdirectory(overlay)
