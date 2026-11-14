#include "ApplicationPaths.h"
#include "AssetProvider.h"
#include "BackendClient.h"
#include "ConfigStore.h"
#include "Controller.h"
#include "ModModel.h"
#include <QDir>
#include <QJsonDocument>
#include <QTemporaryDir>
#include <QtTest>
#include <stdexcept>
#ifdef Q_OS_WIN
#define NOMINMAX
#include <windows.h>
#endif

class CoreTests : public QObject
{
    Q_OBJECT
  private slots:

    void sourceCheckoutUsesLocalDataWithoutCreatingIt()
    {
        QTemporaryDir temp;
        QDir project(temp.path());
        QVERIFY(project.mkpath("src/bridge"));
        for (const auto& name : {"CMakeLists.txt", "src/bridge/worker.py"})
        {
            QFile file(project.filePath(name));
            QVERIFY(file.open(QIODevice::WriteOnly));
        }
        QCOMPARE(ApplicationPaths::dataDirectory(project), temp.path() + "/.local");
        QVERIFY(!QFileInfo::exists(temp.path() + "/.local"));
    }

    void sourceLookupCompletesWhenFoldersWereSavedBeforeItsResponse()
    {
        QTemporaryDir temp;
        QFile source(temp.path() + "/original.nup");
        QVERIFY(source.open(QIODevice::WriteOnly));
        source.close();
        ConfigStore store(temp.path() + "/data", temp.path());
        AssetProvider assets;
        Controller controller(store, QString::fromUtf8(TEST_PYTHON_PATH),
                              QString::fromUtf8(TEST_SNAPSHOT_FIXTURE_PATH), &assets, false);
        controller.initialize();
        QTRY_VERIFY_WITH_TIMEOUT(controller.ready() && !controller.busy(), 5000);
        controller.setSetting("game_dir", temp.path());
        controller.saveSettings();
        QTRY_VERIFY_WITH_TIMEOUT(!controller.busy(), 5000);
        controller.setSetting("jobs", 9);
        QTRY_COMPARE_WITH_TIMEOUT(store.load().value("source").toString(),
                                  QDir::toNativeSeparators(source.fileName()), 5000);
        QCOMPARE(store.load().value("jobs").toInt(), 6);
        QCOMPARE(controller.settings().value("jobs").toInt(), 9);
    }

    void selectedInstallationPrefillsSourceWithoutBlockingOrOverwritingManualEdits()
    {
        QTemporaryDir temp;
        QFile source(temp.path() + "/original.nup");
        QVERIFY(source.open(QIODevice::WriteOnly));
        source.close();
        AssetProvider assets;
        Controller controller(ConfigStore(temp.path() + "/data", temp.path()),
                              QString::fromUtf8(TEST_PYTHON_PATH),
                              QString::fromUtf8(TEST_SNAPSHOT_FIXTURE_PATH), &assets, false);
        controller.initialize();
        QTRY_VERIFY_WITH_TIMEOUT(controller.ready() && !controller.busy(), 5000);
        controller.setSetting("game_dir", temp.path());
        QVERIFY(!controller.busy());
        QTRY_COMPARE_WITH_TIMEOUT(controller.settings().value("source").toString(),
                                  QDir::toNativeSeparators(source.fileName()), 5000);
        QVERIFY(!QFileInfo::exists(temp.path() + "/data/settings.json"));

        // An in-flight lookup must not replace a source typed after the request.
        controller.setSetting("game_dir", temp.path() + "/.");
        QTest::qWait(400);
        controller.setSetting("source", "manual-source.nup");
        QTest::qWait(500);
        QCOMPARE(controller.settings().value("source").toString(), QString("manual-source.nup"));
    }

    void developmentAndPortablePathsStayOutsideSources()
    {
        QTemporaryDir temp;
        QDir project(temp.path());
        QFile config(project.filePath("development.json"));
        QVERIFY(config.open(QIODevice::WriteOnly));
        config.write(R"({"dataDirectory":"../manager-data"})");
        config.close();
        QCOMPARE(ApplicationPaths::dataDirectory(project),
                 QDir::cleanPath(temp.path() + "/../manager-data"));
        QFile flag(project.filePath("portable.flag"));
        QVERIFY(flag.open(QIODevice::WriteOnly));
        flag.close();
        QCOMPARE(ApplicationPaths::dataDirectory(project), temp.path() + "/data");
        QVERIFY(flag.remove());
        QVERIFY(config.open(QIODevice::WriteOnly | QIODevice::Truncate));
        config.write("{}");
        config.close();
        QVERIFY_EXCEPTION_THROWN(ApplicationPaths::dataDirectory(project), std::runtime_error);
    }

    void engineSettingsMigrateWithoutLosingUserPaths()
    {
        QTemporaryDir temp;
        QFile file(temp.path() + "/settings.json");
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.write(
            R"({"longshot":"selected-tools","game_dir":"selected-game","ui_language":"en"})");
        file.close();
        ConfigStore store(temp.path(), temp.path());
        const auto settings = store.load();
        QCOMPARE(settings.value("engine").toString(), QString("longshot"));
        QCOMPARE(settings.value("tools_path").toString(), QString("selected-tools"));
        QCOMPARE(settings.value("game_dir").toString(), QString("selected-game"));
        QCOMPARE(settings.value("ui_language").toString(), QString("en"));
        QVERIFY(!settings.contains("longshot"));
        QVERIFY(store.save(settings));
        QCOMPARE(store.load(), settings);
    }

    void translationCatalogSwitchesAndFallsBack()
    {
        TranslationCatalog catalog;
        QVERIFY(catalog.languages().size() >= 2);
        QVERIFY(catalog.setLanguage("en"));
        QCOMPARE(QCoreApplication::translate("Main", "Bibliothèque"), QString("Library"));
        QCOMPARE(catalog.text("Source du jeu introuvable : G:/Jeu/test.nup"),
                 QString("Game source not found: G:/Jeu/test.nup"));
        QCOMPARE(catalog.text("Unknown technical message"), QString("Unknown technical message"));
        QVERIFY(catalog.setLanguage("fr"));
        QCOMPARE(QCoreApplication::translate("Main", "Bibliothèque"),
                 QString::fromUtf8("Bibliothèque"));
        QCOMPARE(catalog.text("Ready"), QString::fromUtf8("Prêt"));
        QVERIFY(!catalog.setLanguage("../en"));
        QCOMPARE(catalog.language(), QString("fr"));
    }

    void interfaceLanguagePersistsWithoutGamePreferences()
    {
        QTemporaryDir temp;
        ConfigStore store(temp.path(), temp.path());
        auto settings = store.load();
        QCOMPARE(settings.value("ui_language").toString(), QString("en"));
        settings["ui_language"] = "fr";
        settings["game_dir"] = "unchanged-game-folder";
        QVERIFY(store.save(settings));
        AssetProvider assets;
        Controller controller(store, QString::fromUtf8(TEST_PYTHON_PATH),
                              QString::fromUtf8(TEST_SNAPSHOT_FIXTURE_PATH), &assets, false);
        controller.initialize();
        QTRY_VERIFY_WITH_TIMEOUT(controller.ready() && !controller.busy(), 5000);
        QSignalSpy locales(&controller, &Controller::uiLanguageChanged);
        controller.setUiLanguage("en");
        QTRY_VERIFY_WITH_TIMEOUT(!controller.busy(), 5000);
        QCOMPARE(locales.size(), 1);
        QCOMPARE(controller.uiLanguage(), QString("en"));
        QCOMPARE(store.load().value("ui_language").toString(), QString("en"));
        QCOMPARE(store.load().value("game_dir").toString(), QString("unchanged-game-folder"));
        QVERIFY(!store.load().contains("language"));
        controller.applySelected();
        QTRY_VERIFY_WITH_TIMEOUT(!controller.busy(), 5000);
        QCOMPARE(store.load().value("ui_language").toString(), QString("en"));
        controller.setUiLanguage("fr");
        QTRY_VERIFY_WITH_TIMEOUT(!controller.busy(), 5000);
        QCOMPARE(store.load().value("ui_language").toString(), QString("fr"));
    }

    void filteringKeepsStableIds()
    {
        ModModel model;
        model.setRows({QVariantMap{{"id", "wheel"}, {"name", "Roue d’objets"}},
                       QVariantMap{{"id", "shield"}, {"name", "Bouclier"}}});
        QCOMPARE(model.rowCount(), 2);
        model.setFilter("BOUCLIER");
        QCOMPARE(model.rowCount(), 1);
        QCOMPARE(model.get(0).value("id").toString(), "shield");
        QCOMPARE(model.find("wheel").value("name").toString(), QString::fromUtf8("Roue d’objets"));
        model.setFilter("");
        QCOMPARE(model.rowCount(), 2);
        QVERIFY(!model.data(model.index(99), ModModel::ModRole).isValid());
    }

    void configurationNeverWritesLegacy()
    {
        QTemporaryDir temp;
        QDir().mkpath(temp.path() + "/legacy/.gui");
        const auto original =
            QByteArray("{\"game_dir\":\"original\",\"variant\":\"manual-shield\"}");
        QFile file(temp.path() + "/legacy/.gui/settings.json");
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.write(original);
        file.close();
        ConfigStore store(temp.path() + "/new", temp.path() + "/legacy");
        auto settings = store.load();
        QVERIFY(settings.value("game_dir").toString().isEmpty());
        QCOMPARE(settings.value("mods_repo").toString(), temp.path() + "/new/library");
        settings["game_dir"] = "changed";
        QVERIFY(store.save(settings));
        QVERIFY(file.open(QIODevice::ReadOnly));
        QCOMPARE(file.readAll(), original);
        QCOMPARE(store.load().value("game_dir").toString(), "changed");
    }

    void protocolHandlesFragmentedUtf8AndDiagnostics()
    {
        BackendClient client("", "", "", "");
        QSignalSpy events(&client, &BackendClient::eventReceived);
        const auto line = QByteArray("HMBGUI ") +
                          QJsonDocument(QJsonObject{{"type", "log"},
                                                    {"text", QString::fromUtf8("Français : prêt")}})
                              .toJson(QJsonDocument::Compact) +
                          '\n';
        for (const auto c : line)
        {
            client.feed(QByteArray(1, c));
        }
        QCOMPARE(events.size(), 1);
        QCOMPARE(events.first().first().toJsonObject().value("text").toString(),
                 QString::fromUtf8("Français : prêt"));
        client.feed("compiler diagnostic\n");
        QCOMPARE(events.size(), 2);
        QCOMPARE(events.last().first().toJsonObject().value("type").toString(), "log");
    }

    void maskCombinesCoverageAndAlpha()
    {
        QImage image(1, 1, QImage::Format_ARGB32);
        image.fill(qRgba(128, 128, 128, 128));
        const auto tinted = AssetProvider::tint(image, QColor("gold"));
        QCOMPARE(qAlpha(tinted.pixel(0, 0)), 64);
    }

    void protocolLimitAppliesToIndividualLinesNotAValidBatch()
    {
        BackendClient client("", "", "", "");
        QSignalSpy events(&client, &BackendClient::eventReceived);
        client.feed((QByteArray(700000, 'x') + '\n').repeated(7));
        QCOMPARE(events.size(), 7);
        for (const auto& event : events)
        {
            QCOMPARE(event.first().toJsonObject().value("type").toString(), "log");
        }
    }

    void goldTrimDefinesClickableBounds()
    {
        QImage image(20, 12, QImage::Format_ARGB32);
        image.fill(QColor("#604020"));
        for (int x = 3; x < 17; ++x)
        {
            image.setPixelColor(x, 2, QColor("#ddbd75"));
            image.setPixelColor(x, 9, QColor("#ddbd75"));
        }
        QCOMPARE(AssetProvider::goldFrameBounds(image), QRect(3, 2, 14, 8));
    }

    void cancellationTerminatesTheOwnedProcessTree()
    {
#ifdef Q_OS_WIN
        QTemporaryDir temp;
        BackendClient client(QString::fromUtf8(TEST_PYTHON_PATH),
                             QString::fromUtf8(TEST_FIXTURE_PATH), temp.path(), temp.path());
        QSignalSpy events(&client, &BackendClient::eventReceived),
            finished(&client, &BackendClient::finished);
        QVERIFY(client.start({{"action", "fixture"}}));
        QTRY_VERIFY_WITH_TIMEOUT(!events.isEmpty(), 5000);
        const auto child = events.first().first().toJsonObject().value("pid").toInteger();
        QVERIFY(child > 0);
        client.cancel();
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), 1, 5000);
        QVERIFY(finished.first()[1].toBool());
        HANDLE process =
            OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, DWORD(child));
        if (process)
        {
            const auto state = WaitForSingleObject(process, 3000);
            CloseHandle(process);
            QCOMPARE(state, DWORD(WAIT_OBJECT_0));
        }
#else
        QSKIP("Windows process tree contract");
#endif
    }

    void modOptionsSurviveSelectionWithoutLaunchingOperations()
    {
        QTemporaryDir temp;
        AssetProvider assets;
        Controller controller(ConfigStore(temp.path(), temp.path()),
                              QString::fromUtf8(TEST_PYTHON_PATH),
                              QString::fromUtf8(TEST_SNAPSHOT_FIXTURE_PATH), &assets, false);
        QSignalSpy snapshots(&controller, &Controller::snapshotChanged);
        controller.initialize();
        QTRY_VERIFY_WITH_TIMEOUT(controller.ready() && !controller.busy(), 5000);
        QCOMPARE(controller.selected().value("id").toString(), "item-wheel");
        QVERIFY(controller.settings().value("clock").toBool());
        controller.setSetting("hold_ms", 220);
        controller.setSetting("clock", false);
        controller.selectMod("manual-shield");
        controller.selectMod("item-wheel");
        QCOMPARE(controller.settings().value("hold_ms").toInt(), 220);
        QVERIFY(!controller.settings().value("clock").toBool());
        QCOMPARE(snapshots.size(), 1);
        QVERIFY(!QFileInfo::exists(temp.path() + "/settings.json"));
    }

    void importingRefreshesCatalogWithoutLosingSelection()
    {
        QTemporaryDir temp;
        AssetProvider assets;
        Controller controller(ConfigStore(temp.path(), temp.path()),
                              QString::fromUtf8(TEST_PYTHON_PATH),
                              QString::fromUtf8(TEST_SNAPSHOT_FIXTURE_PATH), &assets, false);
        QSignalSpy snapshots(&controller, &Controller::snapshotChanged);
        controller.initialize();
        QTRY_VERIFY_WITH_TIMEOUT(controller.ready() && !controller.busy(), 5000);
        controller.selectMod("manual-shield");
        controller.importArchives({QUrl::fromLocalFile(temp.path() + "/fixture.zip")});
        QTRY_COMPARE_WITH_TIMEOUT(snapshots.size(), 2, 5000);
        QTRY_VERIFY_WITH_TIMEOUT(!controller.busy(), 5000);
        QCOMPARE(controller.selected().value("id").toString(), "manual-shield");
        QVERIFY(!QFileInfo::exists(temp.path() + "/settings.json"));
    }

    void changingLibraryToEmptyFolderClearsCatalogAndSelection()
    {
        QTemporaryDir temp;
        AssetProvider assets;
        Controller controller(ConfigStore(temp.path(), temp.path()),
                              QString::fromUtf8(TEST_PYTHON_PATH),
                              QString::fromUtf8(TEST_SNAPSHOT_FIXTURE_PATH), &assets, false);
        controller.initialize();
        QTRY_VERIFY_WITH_TIMEOUT(controller.ready() && !controller.busy(), 5000);
        QSignalSpy selections(&controller, &Controller::selectionChanged);
        controller.setSetting("mods_repo", temp.path() + "/empty-library");
        controller.saveSettings();
        QTRY_VERIFY_WITH_TIMEOUT(!controller.busy(), 5000);
        QCOMPARE(controller.catalog()->rowCount(), 0);
        QVERIFY(controller.selected().isEmpty());
        QVERIFY(!selections.isEmpty());
    }

    void gamePreferencesAreNotManagerSettings()
    {
        QTemporaryDir temp;
        ConfigStore store(temp.path(), temp.path());
        QVERIFY(store.save({{"language", "fr"}, {"button_prompts", 4}, {"dlss", true}}));
        const auto settings = store.load();
        QVERIFY(!settings.contains("language"));
        QVERIFY(!settings.contains("button_prompts"));
        QVERIFY(!settings.contains("dlss"));
    }
};
QTEST_GUILESS_MAIN(CoreTests)
#include "tst_core.moc"
