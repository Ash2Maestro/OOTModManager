#include "ConfigStore.h"
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QSaveFile>

namespace
{
QJsonObject managerSettings(QJsonObject settings)
{
    if (!settings.contains("tools_path") && settings.contains("longshot"))
    {
        settings["tools_path"] = settings.value("longshot");
    }
    settings.remove("longshot");
    for (const auto& key : {"language", "button_prompts", "dlss", "dlss_license", "ngx_sdk",
                            "data_root", "preserve_runtime_settings", "preserve_longshot_settings",
                            "hookshot", "preserve_hookshot_settings"})
    {
        settings.remove(key);
    }
    return settings;
}
} // namespace

ConfigStore::ConfigStore(QString data, QString core)
    : m_data(QDir::cleanPath(data)), m_core(QDir::cleanPath(core))
{
}

QJsonObject ConfigStore::readObject(const QString& file)
{
    QFile input(file);
    if (!input.open(QIODevice::ReadOnly))
    {
        return {};
    }
    return QJsonDocument::fromJson(input.readAll()).object();
}

QJsonObject ConfigStore::load() const
{
    auto result = readObject(m_data + "/settings.json");
    result = managerSettings(result);
    const QJsonObject defaults{{"source", ""},
                               {"romfs", ""},
                               {"workspace", ""},
                               {"game_dir", ""},
                               {"tools_path", ""},
                               {"engine", "longshot"},
                               {"mods_repo", m_data + "/library"},
                               {"variant", "item-wheel"},
                               {"clock", true},
                               {"hold_ms", 100},
                               {"jobs", 6},
                               {"ui_language", "en"},
                               {"native_cache", m_data + "/cache/native-builds/" +
                                                    result.value("engine").toString("longshot")},
                               {"native_cache_limit_mib", 2048}};
    for (auto it = defaults.begin(); it != defaults.end(); ++it)
    {
        if (!result.contains(it.key()))
        {
            result[it.key()] = it.value();
        }
    }
    return result;
}

bool ConfigStore::save(const QJsonObject& settings, QString* error) const
{
    const auto stored = managerSettings(settings);
    QDir().mkpath(m_data);
    QSaveFile output(m_data + "/settings.json");
    const auto bytes = QJsonDocument(stored).toJson();
    if (!output.open(QIODevice::WriteOnly) || output.write(bytes) != bytes.size() ||
        !output.commit())
    {
        if (error)
        {
            *error = output.errorString();
        }
        return false;
    }
    return true;
}
