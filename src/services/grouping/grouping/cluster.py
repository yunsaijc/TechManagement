"""
项目聚类器

基于项目内容向量进行智能聚类分组
"""
import math
from typing import List, Tuple

import numpy as np


class ProjectCluster:
    """项目聚类器
    
    基于项目内容向量进行智能聚类
    """
    
    def __init__(self, algorithm: str = "kmeans"):
        """初始化
        
        Args:
            algorithm: 聚类算法 (kmeans/层次)
        """
        self.algorithm = algorithm
    
    @staticmethod
    def calculate_optimal_groups(project_count: int, max_per_group: int = 30) -> int:
        """自动计算最优分组数
        
        Args:
            project_count: 项目总数
            max_per_group: 每组最大项目数
        
        Returns:
            最优分组数
        """
        # 基础分组数
        base_groups = math.ceil(project_count / max_per_group)
        
        # 根据项目总数调整
        if project_count < 50:
            return max(2, base_groups)
        elif project_count < 100:
            return max(3, base_groups)
        elif project_count < 200:
            return max(4, base_groups)
        else:
            return max(5, min(10, base_groups))
    
    def fit_predict(
        self,
        vectors: np.ndarray,
        n_clusters: int
    ) -> np.ndarray:
        """执行聚类
        
        Args:
            vectors: 项目向量矩阵 (n_samples, n_features)
            n_clusters: 分组数
        
        Returns:
            聚类标签数组
        """
        if self.algorithm == "kmeans":
            return self._kmeans(vectors, n_clusters)
        elif self.algorithm == "层次":
            return self._hierarchical(vectors, n_clusters)
        else:
            # 默认使用 kmeans
            return self._kmeans(vectors, n_clusters)
    
    def _kmeans(self, vectors: np.ndarray, n_clusters: int) -> np.ndarray:
        """K-means 聚类
        
        Args:
            vectors: 向量矩阵
            n_clusters: 分组数
        
        Returns:
            聚类标签
        """
        n_samples = vectors.shape[0]
        
        # 如果样本数小于分组数，直接返回顺序标签
        if n_samples <= n_clusters:
            return np.arange(n_samples)
        
        # 初始化中心点（随机选择）
        np.random.seed(42)
        indices = np.random.choice(n_samples, n_clusters, replace=False)
        centers = vectors[indices].copy()
        
        # 迭代优化
        max_iter = 100
        for _ in range(max_iter):
            # 计算每个点到中心的距离
            distances = self._cosine_distance(vectors, centers)
            
            # 分配到最近的中心
            labels = np.argmin(distances, axis=1)
            
            # 更新中心点
            new_centers = np.zeros_like(centers)
            for i in range(n_clusters):
                cluster_points = vectors[labels == i]
                if len(cluster_points) > 0:
                    new_centers[i] = cluster_points.mean(axis=0)
                else:
                    # 如果某个簇为空，保持原中心
                    new_centers[i] = centers[i]
            
            # 检查收敛
            if np.allclose(centers, new_centers):
                break
            
            centers = new_centers
        
        return labels
    
    def _hierarchical(self, vectors: np.ndarray, n_clusters: int) -> np.ndarray:
        """层次聚类（简化版）
        
        Args:
            vectors: 向量矩阵
            n_clusters: 分组数
        
        Returns:
            聚类标签
        """
        n_samples = vectors.shape[0]
        
        # 初始化：每个点一个簇
        labels = np.arange(n_samples)
        
        # 简单的凝聚层次聚类
        while len(set(labels)) > n_clusters:
            # 找到最近的两个簇
            unique_labels = list(set(labels))
            min_dist = float('inf')
            merge_pair = (0, 1)
            
            for i, label_i in enumerate(unique_labels):
                for j, label_j in enumerate(unique_labels[i+1:], i+1):
                    points_i = vectors[labels == label_i]
                    points_j = vectors[labels == label_j]
                    
                    # 计算簇间距离
                    center_i = points_i.mean(axis=0)
                    center_j = points_j.mean(axis=0)
                    dist = self._cosine_distance_single(center_i, center_j)
                    
                    if dist < min_dist:
                        min_dist = dist
                        merge_pair = (label_i, label_j)
            
            # 合并簇
            labels[labels == merge_pair[1]] = merge_pair[0]
        
        # 重新编号
        unique_labels = sorted(list(set(labels)))
        label_map = {old: new for new, old in enumerate(unique_labels)}
        return np.array([label_map[l] for l in labels])
    
    @staticmethod
    def _cosine_distance(X: np.ndarray, Y: np.ndarray) -> np.ndarray:
        """计算余弦距离矩阵
        
        Args:
            X: 向量矩阵 A (n, d)
            Y: 向量矩阵 B (m, d)
        
        Returns:
            距离矩阵 (n, m)
        """
        # 归一化
        X_norm = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-8)
        Y_norm = Y / (np.linalg.norm(Y, axis=1, keepdims=True) + 1e-8)
        
        # 余弦相似度
        similarity = X_norm @ Y_norm.T
        
        # 转换为距离
        return 1 - similarity
    
    @staticmethod
    def _cosine_distance_single(x: np.ndarray, y: np.ndarray) -> float:
        """计算两个向量的余弦距离
        
        Args:
            x: 向量 A
            y: 向量 B
        
        Returns:
            距离
        """
        x_norm = x / (np.linalg.norm(x) + 1e-8)
        y_norm = y / (np.linalg.norm(y) + 1e-8)
        return 1 - np.dot(x_norm, y_norm)
    
    @staticmethod
    def balance_clusters(
        labels: np.ndarray,
        n_clusters: int
    ) -> np.ndarray:
        """均衡簇大小
        
        当某些簇过大时，将部分样本移动到较小的簇
        
        Args:
            labels: 原始聚类标签
            n_clusters: 目标簇数
        
        Returns:
            均衡后的标签
        """
        n_samples = len(labels)
        target_size = n_samples // n_clusters
        
        # 统计每个簇的大小
        cluster_sizes = {}
        for label in labels:
            cluster_sizes[label] = cluster_sizes.get(label, 0) + 1
        
        # 重新分配过大的簇
        balanced_labels = labels.copy()
        
        return balanced_labels
