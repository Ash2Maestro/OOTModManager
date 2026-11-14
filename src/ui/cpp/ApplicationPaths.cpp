#include "ApplicationPaths.h"
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStandardPaths>
#include <stdexcept>

QString ApplicationPaths::dataDirectory(const QDir& project)
{
    if (QFile::exists(project.filePath("portable.flag")))
    {
        return project.filePath("data");
    }

    QFile local(project.filePath("development.json"));
    if (local.exists())
    {
        if (!local.open(QIODevice::ReadOnly))
        {
            throw std::runtime_error("Cannot read development.json");
        }
        const auto value =
            QJsonDocument::fromJson(local.readAll()).object().value("dataDirectory").toString();
        if (value.trimmed().isEmpty())
        {
            throw std::runtime_error("development.json requires dataDirectory");
        }
        return QDir::cleanPath(project.absoluteFilePath(value));
    }
    if (project.exists("CMakeLists.txt") && project.exists("src/bridge/worker.py"))
    {
        return project.filePath(".local");
    }
    return QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
}
