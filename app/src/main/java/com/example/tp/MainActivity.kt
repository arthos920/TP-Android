package com.example.tp

import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import coil.compose.rememberImagePainter
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import coil.compose.rememberAsyncImagePainter
import com.example.tp.ui.theme.TPTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            TPTheme {
                // Récupérer le NavController pour gérer la navigation
                val navController = rememberNavController()

                // Créer le host de navigation
                NavHost(navController = navController, startDestination = "product_list") {
                    composable("product_list") {
                        ProductListScreen(navController) // Passe le NavController à l'écran de la liste
                    }
                    composable("product_detail/{productId}") { backStackEntry ->
                        val productId = backStackEntry.arguments?.getString("productId")
                        val product = getProductById(productId) // Récupère le produit avec son ID
                        product?.let {
                            ProductDetailScreen(it)
                        }
                    }
                }
            }
        }
    }

    @Composable
    private fun getProductById(productId: String?): Product? {
        // Accède à l'instance du ViewModel
        val viewModel = viewModel<ProductViewModel>()
        return viewModel.getProductById(productId)
    }
}

@Composable
fun ProductListScreen(navController: NavController, viewModel: ProductViewModel = viewModel()) {
    val products = viewModel.products.collectAsState()
    val categories = viewModel.categories.collectAsState()
    val selectedCategory = viewModel.selectedCategory.collectAsState()

    Column(modifier = Modifier.fillMaxSize()) {
        // Afficher la liste des catégories
        CategorySelector(categories.value, selectedCategory.value) { category ->
            viewModel.filterByCategory(category) // Met à jour les produits selon la catégorie
        }

        // Afficher les produits filtrés
        LazyColumn(modifier = Modifier.fillMaxSize().padding(16.dp)) {
            items(products.value) { product ->
                // Lorsqu'un produit est cliqué, on navigue vers l'écran de détail
                ProductItem(product) {
                    navController.navigate("product_detail/${product.id}")
                }
            }
        }
    }
}


    @Composable
    fun ProductItem(product: Product, onClick: () -> Unit) {
        Row(modifier = Modifier.fillMaxWidth().padding(8.dp).clickable { onClick() }) {
            Image(
                painter = rememberImagePainter(product.image),
                contentDescription = null,
                modifier = Modifier.size(64.dp)
            )
            Spacer(modifier = Modifier.width(16.dp))
            Column(modifier = Modifier.align(Alignment.CenterVertically)) {
                Text(text = product.title, style = MaterialTheme.typography.bodyLarge)
                Text(text = "${product.price} €", style = MaterialTheme.typography.bodyMedium)
            }
        }
    }

@Composable
fun CategorySelector(categories: List<String>, selectedCategory: String?, onCategorySelected: (String?) -> Unit) {
    Column {
        Text(
            text = "Categories",
            style = MaterialTheme.typography.headlineSmall, // Choisir un style adéquat
            modifier = Modifier.padding(16.dp)
        )

        // Ajouter un bouton "All" pour afficher tous les produits
        Button(onClick = { onCategorySelected(null) }) {
            Text("All")
        }

        // Afficher les autres catégories
        categories.forEach { category ->
            Button(onClick = { onCategorySelected(category) }) {
                Text(category)
            }
        }
    }
}
@Composable
fun ProductDetailScreen(product: Product) {
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        // Afficher l'image du produit
        Image(
            painter = rememberAsyncImagePainter(product.image),
            contentDescription = null,
            modifier = Modifier
                .fillMaxWidth()
                .height(250.dp) // Ajuste la taille de l'image selon tes besoins
                .padding(bottom = 16.dp),
            contentScale = ContentScale.Crop
        )

        // Afficher le titre du produit
        Text(
            text = product.title,
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(bottom = 8.dp)
        )

        // Afficher le prix du produit
        Text(
            text = "Price: \$${product.price}",
            style = MaterialTheme.typography.bodyLarge,
            modifier = Modifier.padding(bottom = 8.dp)
        )

        // Afficher la description du produit
        Text(
            text = product.description,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.padding(bottom = 16.dp)
        )

        // Afficher la catégorie du produit
        Text(
            text = "Category: ${product.category}",
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.padding(bottom = 8.dp)
        )

        // Afficher les évaluations
        Text(
            text = "Rating: ${product.rating.rate} (${product.rating.count} reviews)",
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.padding(bottom = 8.dp)
        )
    }
}




