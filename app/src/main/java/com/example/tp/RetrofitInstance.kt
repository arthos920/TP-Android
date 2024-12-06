package com.example.tp

import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

object RetrofitApi {

    private const val BASE_URL = "https://fakestoreapi.com/"

    // Fonction pour obtenir l'instance du service Retrofit
    fun getService(): ApiService {
        // Crée un client OkHttp avec un timeout (optionnel)
        val okHttpClient = OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS) // Timeout de connexion
            .readTimeout(30, TimeUnit.SECONDS)    // Timeout de lecture
            .writeTimeout(30, TimeUnit.SECONDS)   // Timeout d'écriture
            .build()

        // Configure Retrofit avec le client OkHttp
        val retrofit = Retrofit.Builder()
            .baseUrl(BASE_URL) // L'URL de base de l'API
            .client(okHttpClient) // Ajout du client OkHttp
            .addConverterFactory(GsonConverterFactory.create()) // Utilisation de Gson pour la conversion JSON
            .build()

        // Retourne le service Retrofit
        return retrofit.create(ApiService::class.java)
    }
}
