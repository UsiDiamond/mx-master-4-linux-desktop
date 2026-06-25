add_library(mx4hidpp SHARED
    src/hidpp_device.cpp
    src/feature_index.cpp
    src/haptics.cpp
    src/trigger.cpp
)

add_library(mx4hidpp::mx4hidpp ALIAS mx4hidpp)

target_include_directories(mx4hidpp
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

target_link_libraries(mx4hidpp
    PUBLIC
        Hidapi::Hidapi
)

set_target_properties(mx4hidpp PROPERTIES
    VERSION   ${PROJECT_VERSION}
    SOVERSION ${PROJECT_VERSION_MAJOR}
    CXX_STANDARD 20
    CXX_STANDARD_REQUIRED ON
)

install(TARGETS mx4hidpp
    LIBRARY DESTINATION ${KDE_INSTALL_LIBDIR}
)
install(DIRECTORY include/mx4hidpp
    DESTINATION ${KDE_INSTALL_INCLUDEDIR}
)
