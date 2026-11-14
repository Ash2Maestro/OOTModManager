#pragma once
#include "AssetProvider.h"
#include "BackendClient.h"
#include "ConfigStore.h"
#include "ModModel.h"
#include "TranslationCatalog.h"
#include <QStringList>
#include <QTimer>
#include <QUrl>

// Application state and commands. Views never open files or run a shell.
class Controller final : public QObject
{
    Q_OBJECT
    Q_PROPERTY(ModModel* catalog READ catalog CONSTANT)
    Q_PROPERTY(ModModel* installed READ installed CONSTANT)
    Q_PROPERTY(QVariantMap settings READ settings NOTIFY settingsChanged)
    Q_PROPERTY(QVariantMap selected READ selected NOTIFY selectionChanged)
    Q_PROPERTY(QVariantMap state READ state NOTIFY stateChanged)
    Q_PROPERTY(QVariantMap release READ release NOTIFY releaseChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(bool ready READ ready NOTIFY snapshotChanged)
    Q_PROPERTY(bool demo READ demo CONSTANT)
    Q_PROPERTY(bool assetsReady READ assetsReady NOTIFY assetsChanged)
    Q_PROPERTY(int assetRevision READ assetRevision NOTIFY assetsChanged)
    Q_PROPERTY(QString bodyFont READ bodyFont NOTIFY assetsChanged)
    Q_PROPERTY(QString titleFont READ titleFont NOTIFY assetsChanged)
    Q_PROPERTY(QString logText READ logText NOTIFY logChanged)
    Q_PROPERTY(bool forceBuild READ forceBuild WRITE setForceBuild NOTIFY buildOptionsChanged)
    Q_PROPERTY(QString uiLanguage READ uiLanguage NOTIFY uiLanguageChanged)
    Q_PROPERTY(QVariantList uiLanguages READ uiLanguages CONSTANT)
  public:
    Controller(ConfigStore store, QString python, QString bridge, AssetProvider* assets, bool demo,
               QObject* parent = nullptr);
    void loadAssets(const QString& path);

    ModModel* catalog()
    {
        return &m_catalog;
    }

    ModModel* installed()
    {
        return &m_installed;
    }

    QVariantMap settings() const
    {
        return m_settings.toVariantMap();
    }

    QVariantMap selected() const
    {
        return m_selected;
    }

    QVariantMap state() const
    {
        auto result = m_state;
        for (const auto& key : {"status", "stage", "detail", "plan", "warning"})
        {
            result[key] = m_translations.text(result.value(key).toString());
        }
        return result;
    }

    QString uiLanguage() const
    {
        return m_translations.language();
    }

    QVariantList uiLanguages() const
    {
        return m_translations.languages();
    }

    Q_INVOKABLE void setUiLanguage(const QString& language);

    QVariantMap release() const
    {
        return m_release;
    }

    bool busy() const
    {
        return m_busy;
    }

    bool ready() const
    {
        return m_ready;
    }

    bool demo() const
    {
        return m_demo;
    }

    bool assetsReady() const
    {
        return m_assetsReady;
    }

    int assetRevision() const
    {
        return m_assetRevision;
    }

    QString bodyFont() const
    {
        return m_bodyFont;
    }

    QString titleFont() const
    {
        return m_titleFont;
    }

    QString logText() const
    {
        return m_log.join('\n');
    }

    bool forceBuild() const
    {
        return m_forceBuild;
    }

    void setForceBuild(bool value)
    {
        if (m_forceBuild != value)
        {
            m_forceBuild = value;
            emit buildOptionsChanged();
        }
    }

    void initialize();
    Q_INVOKABLE void selectMod(const QString& id);

    Q_INVOKABLE void filter(const QString& query)
    {
        m_catalog.setFilter(query);
    }

    Q_INVOKABLE void setSetting(const QString& key, const QVariant& value);
    Q_INVOKABLE void setPath(const QString& key, const QUrl& url);
    Q_INVOKABLE void saveSettings();
    Q_INVOKABLE void importArchives(const QList<QUrl>& urls);
    Q_INVOKABLE void applySelected(bool force = false);
    Q_INVOKABLE void removeMod(const QString& identifier);
    Q_INVOKABLE void removeLibraryEntry(const QString& identifier, const QString& repository);
    Q_INVOKABLE void restoreVanilla();
    Q_INVOKABLE void checkUpdates(bool includeBeta);
    Q_INVOKABLE void installUpdate();
    Q_INVOKABLE void openRelease();
    Q_INVOKABLE void play();
    Q_INVOKABLE void openLog();
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void cancel();
  signals:
    void settingsChanged();
    void uiLanguageChanged();
    void selectionChanged();
    void stateChanged();
    void releaseChanged();
    void snapshotChanged();
    void busyChanged();
    void assetsChanged();
    void logChanged();
    void buildOptionsChanged();
    void messageRequested(const QString& title, const QString& text);

  private:
    void start(QString action, QJsonObject parameters = {});
    void receive(const QJsonObject& event);
    void finish(int code, bool cancelled);
    void acceptSnapshot(const QJsonObject& event);
    void selectCatalogMod(const QString& id);
    void updateState(const QString& key, const QVariant& value);
    void appendLog(const QString& line);
    void setBusy(bool value);
    void simulate(const QString& action);
    ConfigStore m_store;
    BackendClient m_backend;
    BackendClient m_sourceLookup;
    AssetProvider* m_assets;
    ModModel m_catalog, m_installed;
    QJsonObject m_settings, m_pendingSettings;
    TranslationCatalog m_translations;
    QVariantMap m_selected, m_state, m_release;
    QHash<QString, QVariantMap> m_modOptions;
    QStringList m_log;
    QStringList m_launchCommand;
    QString m_launchDirectory;
    QTimer m_stateTimer, m_logTimer, m_demoTimer, m_sourceTimer;
    QString m_action, m_bodyFont = "Segoe UI", m_titleFont = "Georgia";
    bool m_demo, m_busy = false, m_ready = false, m_assetsReady = false, m_error = false;
    bool m_forceBuild = false, m_workspaceExplicit = false;
    int m_assetRevision = 0, m_demoStep = 0;
    qsizetype m_logCharacters = 0;
};
