set(DAEMON_SOURCES
    src/main.cpp
    src/daemon.cpp
    src/daemon.h
    src/notifications_source.cpp
    src/notifications_source.h
)

# Generate Qt D-Bus adaptor from the XML introspection file.
# The include path given to the adaptor generator must point to the header
# that defines the adaptee class (MX4Daemon).  Pass it with the full path so
# it resolves regardless of include_directories state.
qt6_add_dbus_adaptor(DAEMON_SOURCES
    ${CMAKE_SOURCE_DIR}/cmake/MX4DBus.xml
    ${CMAKE_CURRENT_SOURCE_DIR}/src/daemon.h
    MX4Daemon
)

add_executable(mx4d ${DAEMON_SOURCES})

target_link_libraries(mx4d
    PRIVATE
        mx4hidpp::mx4hidpp
        Qt6::Core
        Qt6::DBus
)

set_target_properties(mx4d PROPERTIES
    CXX_STANDARD 20
    CXX_STANDARD_REQUIRED ON
)

install(TARGETS mx4d
    RUNTIME DESTINATION ${KDE_INSTALL_BINDIR}
)

# Install the D-Bus service activation file
configure_file(
    ${CMAKE_SOURCE_DIR}/cmake/MX4DBus.xml
    ${CMAKE_CURRENT_BINARY_DIR}/org.snapdragon.MX4Daemon1.xml
    COPYONLY
)
