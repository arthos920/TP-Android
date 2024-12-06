package com.example.tp

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class ProductViewModel(private val apiService: ApiService = RetrofitApi.getService()) : ViewModel() {
    private val _products = MutableStateFlow<List<Product>>(emptyList())
    val products: StateFlow<List<Product>> = _products

    private val _categories = MutableStateFlow<List<String>>(emptyList())
    val categories: StateFlow<List<String>> = _categories

    private val _selectedCategory = MutableStateFlow<String?>(null)
    val selectedCategory: StateFlow<String?> = _selectedCategory

    init {
        fetchData()
    }

    private fun fetchData() {
        viewModelScope.launch {
            try {
                val fetchedData = apiService.getData()
                _products.value = fetchedData
                val uniqueCategories = fetchedData.map { it.category }.distinct()
                _categories.value = uniqueCategories
                Log.d("ProductViewModel", "Fetched ${fetchedData.size} products, ${uniqueCategories.size} categories")
            } catch (e: Exception) {
                Log.e("ProductViewModel", "Error fetching products: ${e.message}", e)
            }
        }
    }

    // Ajouter une fonction pour récupérer un produit par ID
    fun getProductById(productId: String?): Product? {
        return _products.value.find { it.id.toString() == productId }
    }

    // Fonction pour filtrer les produits par catégorie
    fun filterByCategory(category: String?) {
        _selectedCategory.value = category
        viewModelScope.launch {
            try {
                _products.value = if (category == null) {
                    apiService.getData()
                } else {
                    apiService.getProductsByCategory(category)
                }
            } catch (e: Exception) {
                Log.e("ProductViewModel", "Error fetching products by category: ${e.message}", e)
            }
        }
    }
}



