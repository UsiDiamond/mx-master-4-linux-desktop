cmake_minimum_required(VERSION 3.16)

project(mx4-radial
    VERSION 0.1.0
    DESCRIPTION "MX Master 4 Linux Desktop radial menu overlay"
    LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "Build type" FORCE)
endif()

# --- Install dir layout ---------------------------------------------------
# Prefer ECM/KDEInstallDirs when present (so we land in the same prefixes as
# the rest of a Plasma install), but never hard-depend on ECM: fall back to
# the always-available GNUInstallDirs so the build stays green everywhere.
find_package(ECM CONFIG QUIET)
if(ECM_FOUND)
    list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
    include(KDEInstallDirs)
    message(STATUS "mx4-radial: using ECM / KDEInstallDirs")
else()
    include(GNUInstallDirs)
    message(STATUS "mx4-radial: ECM not found, using GNUInstallDirs")
endif()

# --- Qt6 ------------------------------------------------------------------
find_package(Qt6 6.4 REQUIRED COMPONENTS
    Core
    Gui
    Qml
    Quick
    DBus)

# --- LayerShellQt (Wayland layer-shell surface) ---------------------------
# Optional at configure time: on a pure-X11 box you can still build/run the
# X11 path. We compile the Wayland code only when the package is found.
find_package(LayerShellQt CONFIG QUIET)
if(LayerShellQt_FOUND)
    message(STATUS "mx4-radial: LayerShellQt found, Wayland layer-shell enabled")
else()
    message(WARNING "mx4-radial: LayerShellQt NOT found, building X11-only overlay")
endif()

# --- Target ---------------------------------------------------------------
set(MX4_SOURCES
    src/main.cpp
    src/RadialController.cpp
    src/RadialController.h
    src/DaemonHaptics.cpp
    src/DaemonHaptics.h
    src/MenuConfig.cpp
    src/MenuConfig.h
    src/PlatformWindow.cpp
    src/PlatformWindow.h
    src/OverlayService.cpp
    src/OverlayService.h
    src/MprisController.cpp
    src/MprisController.h
    qml/qml.qrc
)

add_executable(mx4-radial ${MX4_SOURCES})

target_link_libraries(mx4-radial PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Qml
    Qt6::Quick
    Qt6::DBus)

if(LayerShellQt_FOUND)
    target_link_libraries(mx4-radial PRIVATE LayerShellQt::Interface)
    target_compile_definitions(mx4-radial PRIVATE MX4_HAVE_LAYERSHELL=1)
endif()

# --- Install --------------------------------------------------------------
install(TARGETS mx4-radial
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
