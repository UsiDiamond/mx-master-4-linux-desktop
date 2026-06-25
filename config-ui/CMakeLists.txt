cmake_minimum_required(VERSION 3.16)

project(mx4-config
    VERSION 0.1.0
    DESCRIPTION "MX Master 4 desktop settings GUI"
    LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "Build type" FORCE)
endif()

# --- Install dir layout ---------------------------------------------------
# Prefer ECM/KDEInstallDirs when present (lands in the same prefixes as a
# Plasma install) but never hard-depend on it: fall back to GNUInstallDirs so
# the build stays green on LXQt / minimal setups.
find_package(ECM CONFIG QUIET)
if(ECM_FOUND)
    list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
    include(KDEInstallDirs)
    message(STATUS "mx4-config: using ECM / KDEInstallDirs")
else()
    include(GNUInstallDirs)
    message(STATUS "mx4-config: ECM not found, using GNUInstallDirs")
endif()

# --- Qt6 ------------------------------------------------------------------
# QuickControls2 gives us the Controls 2 forms; it is required for the GUI.
# We verify it explicitly at configure time so a missing component fails loudly
# rather than at link time.
find_package(Qt6 6.4 REQUIRED COMPONENTS
    Core
    Gui
    Qml
    Quick
    DBus)

find_package(Qt6 6.4 QUIET COMPONENTS QuickControls2)
if(Qt6QuickControls2_FOUND)
    message(STATUS "mx4-config: Qt6 QuickControls2 found")
else()
    # Controls 2 is part of qtdeclarative; if the CMake component package is
    # absent (some distro splits) the QML import may still resolve at runtime.
    # Warn but continue, linking only the core Quick libs.
    message(WARNING "mx4-config: Qt6 QuickControls2 CMake package NOT found; "
                    "relying on the runtime QML import "
                    "(install qt6-quickcontrols2 if the app shows blank controls)")
endif()

# --- Target ---------------------------------------------------------------
set(MX4_CONFIG_SOURCES
    src/main.cpp
    src/ConfigModel.cpp
    src/ConfigModel.h
    src/DaemonBridge.cpp
    src/DaemonBridge.h
    qml/qml.qrc
)

add_executable(mx4-config ${MX4_CONFIG_SOURCES})

target_link_libraries(mx4-config PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Qml
    Qt6::Quick
    Qt6::DBus)

if(Qt6QuickControls2_FOUND)
    target_link_libraries(mx4-config PRIVATE Qt6::QuickControls2)
endif()

# --- Install --------------------------------------------------------------
install(TARGETS mx4-config
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})

# Desktop launcher so the app shows in menus / KCM-style search.
install(FILES mx4-config.desktop
    DESTINATION ${CMAKE_INSTALL_DATAROOTDIR}/applications)
