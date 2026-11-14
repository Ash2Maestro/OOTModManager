cmake_minimum_required(VERSION 3.24)
file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/VERSION.txt" MANAGER_VERSION LIMIT_COUNT 1)
project(OOTModManager VERSION ${MANAGER_VERSION} LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui Qml Quick QuickControls2 Test)
qt_standard_project_setup(REQUIRES 6.8)

qt_add_library(manager_core STATIC
    src/ui/cpp/ApplicationPaths.cpp src/ui/cpp/ApplicationPaths.h
    src/ui/cpp/ModModel.cpp src/ui/cpp/ModModel.h src/ui/cpp/ConfigStore.cpp src/ui/cpp/ConfigStore.h
    src/ui/cpp/BackendClient.cpp src/ui/cpp/BackendClient.h src/ui/cpp/Controller.cpp src/ui/cpp/Controller.h
    src/ui/cpp/AssetProvider.cpp src/ui/cpp/AssetProvider.h)
target_sources(manager_core PRIVATE src/ui/cpp/TranslationCatalog.cpp src/ui/cpp/TranslationCatalog.h)
file(GLOB translation_catalogs CONFIGURE_DEPENDS RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}" "i18n/*.json")
qt_add_resources(manager_core "translations" PREFIX "/" FILES ${translation_catalogs})
target_link_libraries(manager_core PUBLIC Qt6::Core Qt6::Gui Qt6::Quick)
target_include_directories(manager_core PUBLIC src/ui/cpp)
if(MSVC)
    target_compile_options(manager_core PRIVATE /W4 /utf-8)
endif()
qt_add_executable(OOTModManager src/ui/cpp/main.cpp)
target_link_libraries(OOTModManager PRIVATE manager_core Qt6::QuickControls2)
set_target_properties(OOTModManager PROPERTIES WIN32_EXECUTABLE TRUE)
set_source_files_properties(src/ui/qml/Theme.qml PROPERTIES QT_QML_SINGLETON_TYPE TRUE)
qt_add_qml_module(OOTModManager URI OOT.Manager VERSION 1.0
    QML_FILES src/ui/qml/Main.qml src/ui/qml/Theme.qml src/ui/qml/GameButton.qml src/ui/qml/OrnamentFrame.qml
    src/ui/qml/MenuHeader.qml src/ui/qml/SubNavigation.qml src/ui/qml/ModList.qml src/ui/qml/GameScrollBar.qml
    src/ui/qml/LibraryPage.qml src/ui/qml/MissionCard.qml src/ui/qml/InstalledPage.qml src/ui/qml/SettingsPage.qml
    src/ui/qml/PathField.qml src/ui/qml/TechnicalDialog.qml src/ui/qml/UpdatePane.qml
    src/ui/qml/GameTextField.qml src/ui/qml/GameComboBox.qml src/ui/qml/GameCheckBox.qml src/ui/qml/GameSpinBox.qml)
target_compile_definitions(OOTModManager PRIVATE MANAGER_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")
target_compile_definitions(OOTModManager PRIVATE MANAGER_VERSION="${PROJECT_VERSION}")
if(MSVC)
    target_compile_options(OOTModManager PRIVATE /utf-8)
endif()
enable_testing()
qt_add_executable(manager_tests tests/tst_core.cpp)
target_link_libraries(manager_tests PRIVATE manager_core Qt6::Test)
target_compile_definitions(manager_tests PRIVATE
    TEST_PYTHON_PATH="${CMAKE_CURRENT_SOURCE_DIR}/.tools/python/Scripts/python.exe"
    TEST_FIXTURE_PATH="${CMAKE_CURRENT_SOURCE_DIR}/tests/process_fixture.py"
    TEST_SNAPSHOT_FIXTURE_PATH="${CMAKE_CURRENT_SOURCE_DIR}/tests/snapshot_fixture.py")
add_test(NAME core COMMAND manager_tests)

if(MSVC)
    target_compile_options(manager_tests PRIVATE /utf-8)
endif()
