set(OVERLAY_SOURCES
    src/main.cpp
    src/radial_window.cpp
    src/radial_window.h
)

add_executable(mx4-radial ${OVERLAY_SOURCES})

# QML resources — must be added after the target is defined
qt6_add_resources(mx4-radial "overlay_qml"
    PREFIX "/qml"
    FILES
        qml/RadialMenu.qml
)

target_link_libraries(mx4-radial
    PRIVATE
        Qt6::Core
        Qt6::DBus
        Qt6::Widgets
        Qt6::Quick
)

set_target_properties(mx4-radial PROPERTIES
    CXX_STANDARD 20
    CXX_STANDARD_REQUIRED ON
)

install(TARGETS mx4-radial
    RUNTIME DESTINATION ${KDE_INSTALL_BINDIR}
)
