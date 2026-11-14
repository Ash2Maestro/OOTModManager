#include "ApplicationPaths.h"
#include "Controller.h"
#include <QCommandLineParser>
#include <QDebug>
#include <QDir>
#include <QDragEnterEvent>
#include <QDragMoveEvent>
#include <QDropEvent>
#include <QElapsedTimer>
#include <QFile>
#include <QGuiApplication>
#include <QMimeData>
#include <QMutex>
#include <QQmlApplicationEngine>
#include <QQuickWindow>
#include <QTimer>
#include <cstdio>

namespace
{
QFile runtimeLog;
QMutex logMutex;

bool smokeArchiveDrop(QQuickWindow* window, Controller& controller)
{
    // Exercise the real Qt DropArea event path in demo mode; no fixture is opened.
    QMimeData mime;
    mime.setUrls({QUrl::fromLocalFile(QDir::tempPath() + "/longshot-smoke.zip")});
    const QPoint position(50, 50);
    QDragEnterEvent enter(position, Qt::CopyAction, &mime, Qt::LeftButton, Qt::NoModifier);
    QCoreApplication::sendEvent(window, &enter);
    QDragMoveEvent move(position, Qt::CopyAction, &mime, Qt::LeftButton, Qt::NoModifier);
    QCoreApplication::sendEvent(window, &move);
    QDropEvent drop(position, Qt::CopyAction, &mime, Qt::LeftButton, Qt::NoModifier);
    QCoreApplication::sendEvent(window, &drop);
    const bool passed = enter.isAccepted() && drop.isAccepted() && controller.busy();
    controller.cancel();
    return passed;
}

void writeLog(QtMsgType, const QMessageLogContext&, const QString& message)
{
    const auto bytes = message.toUtf8();
    QMutexLocker guard(&logMutex);
    if (runtimeLog.isOpen())
    {
        runtimeLog.write(bytes);
        runtimeLog.write("\n");
        runtimeLog.flush();
    }
    std::fprintf(stderr, "%s\n", bytes.constData());
}
} // namespace

int main(int argc, char* argv[])
{
    QElapsedTimer elapsed;
    elapsed.start();
    QGuiApplication app(argc, argv);
    app.setApplicationName("OOTModManager");
    app.setOrganizationName("");
    app.setApplicationVersion(MANAGER_VERSION);
    QCommandLineParser parser;
    parser.addHelpOption();
    parser.addVersionOption();
    QString defaultRoot = QString::fromUtf8(MANAGER_SOURCE_DIR);
    QDir candidate(QCoreApplication::applicationDirPath());
    for (int depth = 0; depth < 4; ++depth)
    {
        if (QFile::exists(candidate.filePath("src/bridge/worker.py")))
        {
            defaultRoot = candidate.absolutePath();
            break;
        }
        if (!candidate.cdUp())
        {
            break;
        }
    }
    parser.addOptions(
        {QCommandLineOption("project-root", "Dossier du projet natif", "path", defaultRoot),
         QCommandLineOption("core", "Dossier du cœur Python", "path"),
         QCommandLineOption("python", "Interpréteur du moteur", "path"),
         QCommandLineOption("data", "Réglages et journaux de cette interface", "path"),
         QCommandLineOption("demo", "Démonstration sans modification du jeu"),
         QCommandLineOption("smoke",
                            "Vérifier le démarrage et la navigation, puis quitter en démo"),
         QCommandLineOption("smoke-language", "Langue du test de l'interface", "language"),
         QCommandLineOption(
             "smoke-size", "Taille logique de la fenêtre de test, par exemple 2560x1440", "size")});
    parser.process(app);
    const QDir root(parser.value("project-root"));
    const auto core =
        parser.isSet("core") ? parser.value("core") : root.absoluteFilePath("src/core");
    QString data;
    try
    {
        data = parser.isSet("data") ? parser.value("data") : ApplicationPaths::dataDirectory(root);
    }
    catch (const std::exception& error)
    {
        qCritical("%s", error.what());
        return 2;
    }
    const auto bundledPython = root.absoluteFilePath("runtime/python.exe");
    const auto python = parser.isSet("python") ? parser.value("python")
                        : QFile::exists(bundledPython)
                            ? bundledPython
                            : root.filePath(".tools/engine-python/Scripts/python.exe");
    QDir().mkpath(data + "/logs");
    runtimeLog.setFileName(data + "/logs/runtime.log");
    runtimeLog.open(QIODevice::WriteOnly | QIODevice::Truncate);
    qInstallMessageHandler(writeLog);
    auto* assets = new AssetProvider;
    Controller controller(ConfigStore(data, core), python, root.filePath("src/bridge/worker.py"),
                          assets, parser.isSet("demo") || parser.isSet("smoke"));
    controller.loadAssets(root.filePath("assets"));
    qmlRegisterSingletonInstance("OOT.Backend", 1, 0, "Manager", &controller);
    QQmlApplicationEngine engine;
    QObject::connect(&controller, &Controller::uiLanguageChanged, &engine,
                     &QQmlEngine::retranslate);
    engine.addImageProvider("art", assets);
    int warnings = 0;
    QObject::connect(&engine, &QQmlApplicationEngine::warnings, &app,
                     [&warnings](const QList<QQmlError>& errors)
                     {
                         warnings += int(errors.size());
                     });
    engine.loadFromModule("OOT.Manager", "Main");
    if (engine.rootObjects().isEmpty())
    {
        return 1;
    }
    auto* window = qobject_cast<QQuickWindow*>(engine.rootObjects().first());
    if (window && parser.isSet("smoke-size"))
    {
        const auto size = parser.value("smoke-size").split('x');
        if (size.size() == 2)
        {
            window->setWidth(size[0].toInt());
            window->setHeight(size[1].toInt());
        }
    }
    if (window)
    {
        QObject::connect(window, &QQuickWindow::frameSwapped, &app,
                         [&, reported = false]() mutable
                         {
                             if (!reported)
                             {
                                 reported = true;
                                 qInfo() << "First frame in" << elapsed.elapsed()
                                         << "ms; graphics API" << QQuickWindow::graphicsApi();
                             }
                         });
    }
    bool reportedReady = false;
    QObject::connect(
        &controller, &Controller::snapshotChanged, &app,
        [&]
        {
            if (!controller.ready() || reportedReady)
            {
                return;
            }
            reportedReady = true;
            qInfo() << "Interface ready in" << elapsed.elapsed() << "ms";
            if (parser.isSet("smoke"))
            {
                QTimer::singleShot(
                    700, &app,
                    [&]
                    {
                        const bool themePresent = controller.assetsReady();
                        qInfo() << "Smoke bundled theme:" << themePresent;
                        if (window)
                        {
                            window->grabWindow().save(data + "/logs/ui-smoke.png");
                        }
                        QVariant passed;
                        QMetaObject::invokeMethod(engine.rootObjects().first(), "runSmokeChecks",
                                                  Q_RETURN_ARG(QVariant, passed));
                        const bool archiveDrop = window && smokeArchiveDrop(window, controller);
                        qInfo() << "Smoke ZIP drop:" << archiveDrop;
                        qInfo() << "Smoke navigation:" << passed.toBool()
                                << "QML warnings:" << warnings;
                        const bool themeValid =
                            !QFile::exists(root.filePath("assets/chronicle.json")) || themePresent;
                        app.exit(passed.toBool() && archiveDrop && themeValid && warnings == 0 ? 0
                                                                                               : 2);
                    });
            }
        });
    if (parser.isSet("smoke"))
    {
        QTimer::singleShot(30000, &app,
                           [&]
                           {
                               qCritical() << "Smoke timeout";
                               app.exit(3);
                           });
    }
    if (parser.isSet("smoke") && parser.isSet("smoke-language"))
    {
        controller.setUiLanguage(parser.value("smoke-language"));
        qInfo() << "Smoke UI language:" << controller.uiLanguage();
    }
    QTimer::singleShot(0, &controller, &Controller::initialize);
    return app.exec();
}
