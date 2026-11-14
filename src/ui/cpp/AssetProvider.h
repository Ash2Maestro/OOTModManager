#pragma once
#include <QHash>
#include <QQuickImageProvider>
#include <QReadWriteLock>

// Decode/tint local artwork once; Qt owns shared GPU textures afterwards.
class AssetProvider final : public QQuickImageProvider
{
  public:
    AssetProvider() : QQuickImageProvider(QQuickImageProvider::Image) {}

    bool load(const QString& directory);
    QImage requestImage(const QString& id, QSize* size, const QSize& requestedSize) override;

    QString directory() const
    {
        return m_directory;
    }

    static QImage tint(const QImage& mask, QColor colour, qreal opacity = 1);
    static QRect goldFrameBounds(const QImage& image);

  private:
    QHash<QString, QImage> m_images;
    QString m_directory;
    QReadWriteLock m_lock;
};
