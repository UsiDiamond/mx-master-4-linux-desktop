# FindHidapi.cmake — locate hidapi-hidraw via pkg-config
# Sets:
#   Hidapi_FOUND
#   Hidapi::Hidapi imported target (SHARED_LIBRARY interface)
#
# pkg-config package name: hidapi-hidraw  (links against the raw backend;
# change to hidapi-libusb if you want the libusb backend instead)

include(FindPackageHandleStandardArgs)

find_package(PkgConfig QUIET)
if(PKG_CONFIG_FOUND)
    pkg_check_modules(PC_HIDAPI QUIET hidapi-hidraw)
endif()

find_path(HIDAPI_INCLUDE_DIR
    NAMES hidapi/hidapi.h
    HINTS ${PC_HIDAPI_INCLUDE_DIRS}
)

find_library(HIDAPI_LIBRARY
    NAMES hidapi-hidraw hidapi
    HINTS ${PC_HIDAPI_LIBRARY_DIRS}
)

find_package_handle_standard_args(Hidapi
    REQUIRED_VARS HIDAPI_LIBRARY HIDAPI_INCLUDE_DIR
    VERSION_VAR   PC_HIDAPI_VERSION
)

if(Hidapi_FOUND AND NOT TARGET Hidapi::Hidapi)
    add_library(Hidapi::Hidapi UNKNOWN IMPORTED)
    set_target_properties(Hidapi::Hidapi PROPERTIES
        IMPORTED_LOCATION             "${HIDAPI_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${HIDAPI_INCLUDE_DIR}"
        INTERFACE_COMPILE_OPTIONS     "${PC_HIDAPI_CFLAGS_OTHER}"
    )
endif()

mark_as_advanced(HIDAPI_INCLUDE_DIR HIDAPI_LIBRARY)
