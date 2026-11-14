#pragma once
#include <QFile>
#include <QJsonObject>
#include <QObject>
#include <QProcess>

// Asynchronous transport only. No QML, domain rules or shell command strings.
class BackendClient final : public QObject
{
    Q_OBJECT
  public:
    explicit BackendClient(QString python, QString bridge, QString core, QString data,
                           QObject* parent = nullptr);
    ~BackendClient() override;
    bool start(const QJsonObject& request);

    bool running() const
    {
        return m_process.state() != QProcess::NotRunning;
    }

    void cancel();
    void feed(const QByteArray& bytes); // Also exercised with fragmented UTF-8 by unit tests.

    QString logFile() const
    {
        return m_log.fileName();
    }

  signals:
    void eventReceived(const QJsonObject& event);
    void finished(int exitCode, bool cancelled);

  private:
    void attachJob();
    void closeJob();
    QProcess m_process;
    QString m_python, m_bridge, m_core, m_data;
    QByteArray m_buffer;
    QFile m_log;
    bool m_cancelled = false;
    void* m_job = nullptr;
};
