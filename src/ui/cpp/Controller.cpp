#include "Controller.h"
#include <QDesktopServices>
#include <QDir>
#include <QFileInfo>
#include <QFontDatabase>
#include <QJsonArray>
#include <QUrl>

namespace
{
QVariantMap wheelOptions(const QJsonObject& settings)
{
    return {{"clock", settings.value("clock").toBool()},
            {"hold_ms", settings.value("hold_ms").toInt(100)}};
}
} // namespace

Controller::Controller(ConfigStore store, QString python, QString bridge, AssetProvider* assets,
                       bool demo, QObject* parent)
    : QObject(parent), m_store(std::move(store)),
      m_backend(python, bridge, m_store.coreDirectory(), m_store.dataDirectory(), this),
      m_sourceLookup(std::move(python), std::move(bridge), m_store.coreDirectory(),
                     m_store.dataDirectory(), this),
      m_assets(assets), m_catalog(this), m_installed(this), m_settings(m_store.load()), m_demo(demo)
{
    m_translations.setLanguage(m_settings.value("ui_language").toString("fr"));
    m_modOptions.insert(m_settings.value("variant").toString(), wheelOptions(m_settings));
    m_state = {{"status", tr("Chargement du catalogue…")},
               {"active", "vanilla"},
               {"activeName", tr("Jeu original")},
               {"progress", -1},
               {"stage", ""},
               {"detail", ""},
               {"warning", ""},
               {"plan", ""}};
    for (auto* timer : {&m_stateTimer, &m_logTimer})
    {
        timer->setSingleShot(true);
        timer->setInterval(33);
    }
    connect(&m_stateTimer, &QTimer::timeout, this, &Controller::stateChanged);
    connect(&m_logTimer, &QTimer::timeout, this, &Controller::logChanged);
    connect(&m_backend, &BackendClient::eventReceived, this, &Controller::receive);
    connect(&m_backend, &BackendClient::finished, this, &Controller::finish);
    // Lookup is read-only and independent of the operation worker. Debounce
    // typed paths and never lock the interface or overwrite a newer manual edit.
    m_sourceTimer.setSingleShot(true);
    m_sourceTimer.setInterval(350);
    connect(&m_sourceTimer, &QTimer::timeout, this,
            [this]
            {
                if (m_demo || m_settings.value("game_dir").toString().trimmed().isEmpty())
                {
                    return;
                }
                if (m_busy || m_sourceLookup.running())
                {
                    m_sourceTimer.start();
                    return;
                }
                m_sourceLookup.start({{"action", "resolve_source"}, {"settings", m_settings}});
            });
    connect(&m_sourceLookup, &BackendClient::eventReceived, this,
            [this](const QJsonObject& event)
            {
                const auto source = event.value("source").toString();
                if (event.value("type") != "source_detected" || source.isEmpty() || m_busy ||
                    event.value("game_dir") != m_settings.value("game_dir") ||
                    event.value("engine") != m_settings.value("engine") ||
                    event.value("previous_source") != m_settings.value("source") ||
                    !QFileInfo(source).isFile())
                {
                    return;
                }
                m_settings["source"] = source;
                emit settingsChanged();
                // Save can finish before this asynchronous response. Update only
                // the source of that same committed installation; never commit
                // the rest of a form the user has not saved yet.
                auto stored = m_store.load();
                if (stored.value("game_dir") == event.value("game_dir") &&
                    stored.value("engine") == event.value("engine") &&
                    stored.value("source") == event.value("previous_source"))
                {
                    stored["source"] = source;
                    QString error;
                    if (!m_store.save(stored, &error))
                    {
                        emit messageRequested(tr("Préférences non enregistrées"), error);
                    }
                }
            });
    m_demoTimer.setInterval(70);
    connect(&m_demoTimer, &QTimer::timeout, this,
            [this]
            {
                updateState("progress", ++m_demoStep * 5);
                if (m_demoStep >= 20)
                {
                    m_demoTimer.stop();
                    appendLog(tr("Démonstration terminée ; aucun fichier du jeu modifié."));
                    finish(0, false);
                }
            });
}

void Controller::initialize()
{
    start("snapshot");
    if (m_settings.value("source").toString().trimmed().isEmpty())
    {
        m_sourceTimer.start();
    }
}

void Controller::setUiLanguage(const QString& language)
{
    if (m_busy || language == uiLanguage() || !m_translations.setLanguage(language))
    {
        return;
    }
    m_settings["ui_language"] = language;
    QString error;
    if (!m_demo && !m_store.save(m_settings, &error))
    {
        emit messageRequested(tr("Enregistrement impossible"), error);
    }
    emit settingsChanged();
    emit uiLanguageChanged();
    emit stateChanged();
    refresh();
}

void Controller::setBusy(bool value)
{
    if (m_busy != value)
    {
        m_busy = value;
        emit busyChanged();
    }
}

void Controller::updateState(const QString& key, const QVariant& value)
{
    if (m_state.value(key) == value)
    {
        return;
    }
    m_state[key] = value;
    if (!m_stateTimer.isActive())
    {
        m_stateTimer.start();
    }
}

void Controller::appendLog(const QString& line)
{
    m_log.append(m_translations.text(line).left(32768));
    m_logCharacters += m_log.last().size();
    while (m_log.size() > 2000 || m_logCharacters > 200000)
    {
        m_logCharacters -= m_log.takeFirst().size();
    }
    if (!m_logTimer.isActive())
    {
        m_logTimer.start();
    }
}

void Controller::loadAssets(const QString& path)
{
    if (path.isEmpty() || path == m_assets->directory())
    {
        return;
    }
    m_assetsReady = m_assets->load(path);
    if (!m_assetsReady)
    {
        return;
    }
    auto family = [](const QString& file, const QString& fallback)
    {
        const int id = QFontDatabase::addApplicationFont(file);
        const auto names = QFontDatabase::applicationFontFamilies(id);
        return names.isEmpty() ? fallback : names.first();
    };
    m_bodyFont = family(path + "/body.otf", "Segoe UI");
    m_titleFont = family(path + "/mission.otf", "Georgia");
    ++m_assetRevision;
    emit assetsChanged();
}

void Controller::acceptSnapshot(const QJsonObject& event)
{
    m_launchCommand.clear();
    for (const auto& argument : event.value("launchCommand").toArray())
    {
        m_launchCommand.append(argument.toString());
    }
    m_launchDirectory = event.value("launchDirectory").toString();
    loadAssets(event.value("assets").toString());
    updateState("active", event.value("active").toString());
    updateState("activeName", event.value("activeName").toString());
    updateState("warning", event.value("warning").toString());
    auto catalog = event.value("catalog").toArray().toVariantList();
    for (auto& value : catalog)
    {
        auto row = value.toMap();
        row["installed"] =
            row.value("installed").toBool() ||
            (row.value("id") == m_state.value("active") &&
             (event.value("activeVersion").toString().isEmpty() ||
              row.value("version").toString() == event.value("activeVersion").toString()));
        value = row;
    }
    m_catalog.setRows(catalog);
    m_installed.setRows(event.value("installed").toArray().toVariantList());
    const QString selection =
        m_selected.value("id", m_settings.value("variant").toVariant()).toString();
    m_selected.clear();
    selectCatalogMod(selection);
    if (m_selected.isEmpty() && m_catalog.rowCount())
    {
        selectCatalogMod(m_catalog.get(0).value("id").toString());
    }
    if (m_selected.isEmpty())
    {
        m_release.clear();
        emit selectionChanged();
        emit releaseChanged();
    }
    m_ready = true;
    emit snapshotChanged();
    if (!m_assetsReady && m_state.value("warning").toString().isEmpty())
    {
        updateState(
            "warning",
            tr("Ressources visuelles absentes : configurez le jeu et les outils dans Paramètres."));
    }
}

void Controller::selectMod(const QString& id)
{
    if (m_busy && m_ready && m_action != "snapshot")
    {
        return;
    }
    selectCatalogMod(id);
}

void Controller::selectCatalogMod(const QString& id)
{
    auto item = m_catalog.find(id);
    if (item.isEmpty() || item == m_selected)
    {
        return;
    }
    if (!m_selected.isEmpty())
    {
        m_modOptions.insert(m_selected.value("id").toString(), wheelOptions(m_settings));
    }
    const auto options = m_modOptions.value(id, {{"clock", id == "item-wheel"}, {"hold_ms", 100}});
    m_modOptions[id] = options;
    m_settings["clock"] = options.value("clock").toBool();
    m_settings["hold_ms"] = options.value("hold_ms").toInt();
    emit settingsChanged();
    m_selected = item;
    m_release.clear();
    emit selectionChanged();
    emit releaseChanged();
}

void Controller::setSetting(const QString& key, const QVariant& value)
{
    if (m_busy || !m_settings.contains(key))
    {
        return;
    }
    if (m_settings.value(key).toVariant() == value)
    {
        return;
    }
    m_settings[key] = QJsonValue::fromVariant(value);
    if (key == "game_dir" || key == "engine")
    {
        m_sourceTimer.start();
    }
    else if (key == "source")
    {
        m_sourceTimer.stop();
    }
    if (key == "workspace")
    {
        m_workspaceExplicit = true;
    }
    if ((key == "clock" || key == "hold_ms") && !m_selected.isEmpty())
    {
        m_modOptions[m_selected.value("id").toString()][key] = value;
    }
    emit settingsChanged();
}

void Controller::setPath(const QString& key, const QUrl& url)
{
    if (url.isLocalFile())
    {
        setSetting(key, QDir::toNativeSeparators(url.toLocalFile()));
    }
}

void Controller::saveSettings()
{
    if (m_busy)
    {
        return;
    }
    QString error;
    if (!m_store.save(m_settings, &error))
    {
        emit messageRequested(tr("Enregistrement impossible"), error);
        return;
    }
    start("snapshot");
}

void Controller::importArchives(const QList<QUrl>& urls)
{
    if (m_busy)
    {
        return;
    }
    if (urls.isEmpty() || urls.size() > 32)
    {
        emit messageRequested(tr("Import ZIP"), tr("Choisissez entre 1 et 32 archives ZIP."));
        return;
    }
    QJsonArray paths;
    for (const auto& url : urls)
    {
        if (!url.isLocalFile() ||
            QFileInfo(url.toLocalFile()).suffix().compare("zip", Qt::CaseInsensitive) != 0)
        {
            emit messageRequested(tr("Import ZIP"),
                                  tr("Seules les archives ZIP locales sont acceptées."));
            return;
        }
        paths.append(url.toLocalFile());
    }
    start("import_zip", {{"archives", paths}});
}

void Controller::start(QString action, QJsonObject parameters)
{
    if (m_busy)
    {
        return;
    }
    m_action = action;
    m_error = false;
    m_pendingSettings = {};
    updateState("action", action);
    setBusy(true);
    updateState("progress", -1);
    updateState("status",
                action == "snapshot" ? tr("Lecture du catalogue…") : tr("Opération en cours"));
    updateState("stage", action == "updates" ? tr("Consultation de GitHub") : tr("Vérification"));
    if (m_demo && action != "snapshot")
    {
        simulate(action);
        return;
    }
    parameters["action"] = action;
    parameters["settings"] = m_settings;
    m_backend.start(parameters);
}

void Controller::simulate(const QString& action)
{
    appendLog(tr("Démonstration : %1. Aucun fichier du jeu ne sera modifié.").arg(action));
    updateState("stage", tr("Démonstration sans compilation"));
    m_demoStep = 0;
    m_demoTimer.start();
}

void Controller::receive(const QJsonObject& event)
{
    const auto type = event.value("type").toString();
    if (type == "snapshot")
    {
        acceptSnapshot(event);
        return;
    }
    if (type == "progress")
    {
        updateState("stage", event.value("label").toString());
        updateState("detail", event.value("detail").toString());
        updateState("progress",
                    event.value("percent").isDouble() ? event.value("percent").toDouble() : -1);
    }
    else if (type == "log")
    {
        appendLog(event.value("text").toString());
    }
    else if (type == "plan")
    {
        updateState("plan", event.value("title").toString());
        appendLog(event.value("reason").toString());
    }
    else if (type == "error")
    {
        m_error = true;
        updateState("status", tr("Échec"));
        appendLog(event.value("message").toString());
        emit messageRequested(tr("L’opération s’est arrêtée"), event.value("message").toString());
    }
    else if (type == "installed")
    {
        m_pendingSettings = event.value("settings").toObject();
    }
    else if (type == "complete")
    {
        appendLog(event.value("message").toString());
    }
    else if (type == "updates_result")
    {
        m_release = event.value("result").toObject().toVariantMap();
        emit releaseChanged();
    }
    else if (type == "import_result")
    {
        const auto count = event.value("imported").toArray().size();
        QStringList names;
        for (const auto& value : event.value("imported").toArray())
        {
            const auto id = value.toString();
            names.append(m_catalog.find(id).value("name", id).toString());
        }
        QStringList errors;
        for (const auto& value : event.value("errors").toArray())
        {
            errors.append(value.toString());
        }
        QString message =
            QString(tr("%1 mod(s) ajouté(s) à la bibliothèque. Aucun changement appliqué au jeu."))
                .arg(count);
        if (!names.isEmpty())
        {
            message += "\n\n" + names.join(", ");
        }
        if (!errors.isEmpty())
        {
            message += tr("\n\nArchives refusées :\n") + errors.join("\n");
        }
        appendLog(message);
        emit messageRequested(tr("Import ZIP terminé"), message);
    }
}

void Controller::finish(int code, bool cancelled)
{
    const auto action = m_action;
    setBusy(false);
    if (cancelled)
    {
        updateState("status", tr("Interrompu — cache conservé"));
        return;
    }
    if (code != 0 || m_error)
    {
        updateState("status", tr("Échec — consulter le journal"));
        if (!m_ready)
        {
            m_ready = true;
            emit snapshotChanged();
        }
        return;
    }
    if (!m_demo && !m_pendingSettings.isEmpty())
    {
        const auto libraryFolder = m_settings.value("mods_repo");
        const auto interfaceLanguage = m_settings.value("ui_language");
        m_settings = m_pendingSettings;
        m_settings["mods_repo"] = libraryFolder;
        m_settings["ui_language"] = interfaceLanguage;
        emit settingsChanged();
        m_workspaceExplicit = false;
        m_modOptions[m_settings.value("variant").toString()] = wheelOptions(m_settings);
    }
    if (!m_demo && !m_pendingSettings.isEmpty())
    {
        QString error;
        if (!m_store.save(m_settings, &error))
        {
            emit messageRequested(tr("Préférences non enregistrées"), error);
        }
    }
    updateState("status", m_demo ? tr("Démo") : tr("Prêt"));
    if (action != "snapshot" && action != "updates")
    {
        updateState("progress", 100);
    }
    if (!m_demo && (action == "apply" || action == "remove" || action == "vanilla" ||
                    action == "update_install"))
    {
        QTimer::singleShot(0, this, &Controller::refresh);
    }
}

void Controller::applySelected(bool force)
{
    if (!m_selected.isEmpty())
    {
        start("apply", {{"variant", m_selected.value("id").toString()},
                        {"repository", m_selected.value("repository").toString()},
                        {"force", force || m_forceBuild},
                        {"preferWorkspace", m_workspaceExplicit}});
    }
}

void Controller::removeMod(const QString& identifier)
{
    if (!identifier.isEmpty())
    {
        start("remove", {{"identifier", identifier}});
    }
}

void Controller::removeLibraryEntry(const QString& identifier, const QString& repository)
{
    if (!identifier.isEmpty() && !repository.isEmpty())
    {
        start("library_remove", {{"identifier", identifier}, {"repository", repository}});
    }
}

void Controller::restoreVanilla()
{
    start("vanilla");
}

void Controller::checkUpdates(bool includeBeta)
{
    if (m_busy || m_selected.isEmpty())
    {
        return;
    }
    m_release.clear();
    emit releaseChanged();
    start("updates", {{"variant", m_selected.value("id").toString()},
                      {"version", m_selected.value("version").toString()},
                      {"includeBeta", includeBeta}});
}

void Controller::installUpdate()
{
    if (!m_release.value("tag").toString().isEmpty())
    {
        start("update_install", {{"variant", m_selected.value("id").toString()},
                                 {"repository", m_selected.value("repository").toString()},
                                 {"tag", m_release.value("tag").toString()}});
    }
}

void Controller::openRelease()
{
    const QUrl url(m_release.value("url").toString());
    if (url.scheme() == "https" && url.host() == "github.com")
    {
        QDesktopServices::openUrl(url);
    }
}

void Controller::play()
{
    if (m_busy || m_demo)
    {
        return;
    }
    if (m_launchDirectory == m_settings.value("game_dir").toString() &&
        !m_launchCommand.isEmpty() && QFileInfo(m_launchCommand.first()).isFile())
    {
        QProcess::startDetached(m_launchCommand.first(), m_launchCommand.mid(1), m_launchDirectory);
        return;
    }
    emit messageRequested(tr("Jeu introuvable"), tr("Vérifiez le dossier de jeu dans Paramètres."));
}

void Controller::refresh()
{
    start("snapshot");
}

void Controller::cancel()
{
    if (!m_busy)
    {
        return;
    }
    if (m_demoTimer.isActive())
    {
        m_demoTimer.stop();
        finish(130, true);
    }
    else
    {
        m_backend.cancel();
    }
}

void Controller::openLog()
{
    const auto file = m_backend.logFile();
    QDesktopServices::openUrl(
        QUrl::fromLocalFile(QFileInfo::exists(file) ? file : m_store.dataDirectory() + "/logs"));
}
