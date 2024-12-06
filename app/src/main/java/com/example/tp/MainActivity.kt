package com.example.tp

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Text
import androidx.compose.runtime.*

import coil.compose.rememberImagePainter
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel


@Composable
fun ProductListScreen() {
    // Initialisation du ViewModel
    val viewModel: ProductViewModel = viewModel()

    // Observer les données du ViewModel
    val products by viewModel.products.collectAsState()

    LazyColumn(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        items(products) { product ->
            ProductItem(product)
            Spacer(modifier = Modifier.height(8.dp))
        }
    }
}

@Composable
fun ProductItem(product: Product) {
    Row(modifier = Modifier.fillMaxWidth()) {
        Image(
            painter = rememberImagePainter(data = product.image),
            contentDescription = null,
            modifier = Modifier.size(64.dp)
        )
        Spacer(modifier = Modifier.width(16.dp))
        Column {
            Text(text = product.title, style = MaterialTheme.typography.body1)
            Text(text = "${product.price} €", style = MaterialTheme.typography.body2)
        }
    }
}


