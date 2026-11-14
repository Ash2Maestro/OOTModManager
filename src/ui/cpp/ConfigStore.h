#pragma once
#include <QJsonObject>
#include <QString>

// Qt settings are private to this migration; core settings are a bootstrap only.
class ConfigStore
{
  public:
    ConfigStore(QString dataDirectory, QString coreDirectory);
    QJsonObject load() const;
    bool save(const QJsonObject& settings, QString* error = nullptr) const;

    QString dataDirectory() const
    {
        return m_data;
    }

    QString coreDirectory() const
    {
        return m_core;
    }

    static QJsonObject readObject(const QString& file);

  private:
    QString m_data, m_core;
};
